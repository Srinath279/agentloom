"""Generic LLM activity, reusable by every agent in the loom.

Temporal best practices applied here:
- Request parameters live in a single dataclass.
- OpenAI client retries are disabled (max_retries=0) so Temporal owns
  retry/backoff semantics instead of the SDK fighting them.
"""

from dataclasses import dataclass

from openai import AsyncOpenAI
from openai.types.responses import Response
from temporalio import activity


@dataclass
class OpenAIResponsesRequest:
    model: str
    instructions: str
    input: str


@activity.defn
async def create(request: OpenAIResponsesRequest) -> Response:
    client = AsyncOpenAI(max_retries=0)

    return await client.responses.create(
        model=request.model,
        instructions=request.instructions,
        input=request.input,
        timeout=15,
    )
