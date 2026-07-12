"""Generic Claude/Anthropic activity, reusable by every agent in the loom.

Temporal best practices applied here:
- Request parameters live in a single dataclass.
- The activity performs a direct Claude HTTP request so Temporal owns retry
  and timeout semantics.
"""

import os
from dataclasses import dataclass

import httpx
from langfuse import get_client, propagate_attributes
from temporalio import activity


@dataclass
class LLMResponsesRequest:
    model: str
    instructions: str
    input: str


@activity.defn
async def create(request: LLMResponsesRequest) -> str:
    info = activity.info()
    langfuse = get_client()

    # One generation per LLM call, grouped into a session per workflow run
    # so all agent steps of a LoomWorkflow show up as one thread in Langfuse.
    with propagate_attributes(
        session_id=info.workflow_id,
        trace_name=info.workflow_type,
        tags=["temporal", "agentloom"],
    ):
        with langfuse.start_as_current_observation(
            name=f"{info.workflow_type}.{info.activity_type}",
            as_type="generation",
            model=request.model,
            input={"instructions": request.instructions, "input": request.input},
            metadata={
                "workflow_id": info.workflow_id,
                "run_id": info.workflow_run_id,
                "activity_id": info.activity_id,
                "attempt": info.attempt,
                "task_queue": info.task_queue,
            },
        ) as generation:
            try:
                output_text = await _call_claude(request)
            except Exception as e:
                generation.update(level="ERROR", status_message=str(e))
                raise
            generation.update(output=output_text)
            return output_text


async def _call_claude(request: LLMResponsesRequest) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing ANTHROPIC_API_KEY environment variable for Claude activity."
        )

    payload = {
        "model": request.model,
        "input": f"{request.instructions}\n\n{request.input}",
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/responses",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    output_text = _claude_output_text(data)
    if not output_text:
        raise RuntimeError(f"Unexpected Claude response format: {data}")
    return output_text


def _claude_output_text(data: dict) -> str:
    if output := data.get("output"):
        if isinstance(output, list):
            texts: list[str] = []
            for part in output:
                if isinstance(part, dict):
                    if part.get("type") == "output_text":
                        texts.append(part.get("text", ""))
                    elif isinstance(part.get("content"), list):
                        for chunk in part["content"]:
                            if chunk.get("type") == "output_text":
                                texts.append(chunk.get("text", ""))
            if texts:
                return "".join(texts)
    if completion := data.get("completion"):
        if isinstance(completion, dict):
            message = completion.get("message", {})
            content = message.get("content", [])
            texts: list[str] = []
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "output_text":
                        texts.append(item.get("text", ""))
            if texts:
                return "".join(texts)
    if text := data.get("output_text"):
        return text
    return ""
