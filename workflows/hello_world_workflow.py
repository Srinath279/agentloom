"""Single-agent starter workflow: one LLM call, in haiku form."""

from datetime import timedelta

from temporalio import workflow

# The activities module imports httpx/langfuse, which the deterministic
# workflow sandbox rejects; pass it through — the workflow only needs the
# activity reference and its request dataclass.
with workflow.unsafe.imports_passed_through():
    from activities import openai_responses


@workflow.defn
class HelloWorld:
    @workflow.run
    async def run(self, input: str) -> str:
        result = await workflow.execute_activity(
            openai_responses.create,
            openai_responses.LLMResponsesRequest(
                model="anthropic/claude-haiku-4.5",
                instructions="You only respond in haikus.",
                input=input,
            ),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return result
