"""Generic LLM activity, reusable by every agent in the loom.

Calls Claude models through OpenRouter's OpenAI-compatible Chat Completions
API.

Temporal best practices applied here:
- Request parameters live in a single dataclass.
- The activity performs a direct HTTP request (no client-side retries) so
  Temporal owns retry and timeout semantics.
"""

import os
from dataclasses import dataclass

import httpx
from langfuse import get_client, propagate_attributes
from temporalio import activity

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


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
                output_text = await _call_openrouter(request)
            except Exception as e:
                generation.update(level="ERROR", status_message=str(e))
                raise
            generation.update(output=output_text)
            return output_text


async def _call_openrouter(request: LLMResponsesRequest) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY environment variable for the LLM activity."
        )

    payload = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.instructions},
            {"role": "user", "content": request.input},
        ],
    }
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}",
        # Optional but recommended by OpenRouter for app attribution/rankings.
        "HTTP-Referer": "https://github.com/agentloom/agentloom",
        "X-Title": "AgentLoom",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    output_text = _openrouter_output_text(data)
    if not output_text:
        raise RuntimeError(f"Unexpected OpenRouter response format: {data}")
    return output_text


def _openrouter_output_text(data: dict) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            return content
    return ""
