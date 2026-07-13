"""Generic LLM activity, reusable by every agent in the loom.

Calls any OpenAI-compatible Chat Completions API — OpenRouter by default,
or a local server (e.g. Ollama) when LLM_BASE_URL is set.

Temporal best practices applied here:
- Request parameters live in a single dataclass.
- The activity performs a direct HTTP request (no client-side retries) so
  Temporal owns retry and timeout semantics.

Environment is read at call time (not import time) so each activity attempt
sees the current configuration and tests can monkeypatch it.
"""

import os
from dataclasses import dataclass

import httpx
from temporalio import activity

from agentloom import config, tracing


@dataclass
class LLMRequest:
    model: str
    instructions: str
    input: str


@activity.defn
async def run_llm(request: LLMRequest) -> str:
    # One Langfuse generation per LLM call, grouped into one session per
    # workflow run — the convention lives in agentloom.tracing.
    with tracing.llm_generation(
        model=request.model,
        input={"instructions": request.instructions, "input": request.input},
    ) as generation:
        output_text = await _call_chat_completions(request)
        generation.update(output=output_text)
        return output_text


async def _call_chat_completions(request: LLMRequest) -> str:
    base_url = os.environ.get("LLM_BASE_URL", config.DEFAULT_LLM_BASE_URL)
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key and base_url == config.DEFAULT_LLM_BASE_URL:
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
        # Optional but recommended by OpenRouter for app attribution/rankings.
        "HTTP-Referer": "https://github.com/agentloom/agentloom",
        "X-Title": "AgentLoom",
    }
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(base_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    output_text = _chat_output_text(data)
    if not output_text:
        raise RuntimeError(f"Unexpected chat completions response format: {data}")
    return output_text


def _chat_output_text(data: dict) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            return content
    return ""
