"""Single-agent starter workflow: one LLM call, in haiku form."""

from datetime import timedelta

from temporalio import workflow

from agentloom.agents import HAIKU_BOT

# The activities module imports httpx/langfuse, which the deterministic
# workflow sandbox rejects; pass it through — the workflow only needs the
# activity reference and its request dataclass.
with workflow.unsafe.imports_passed_through():
    from agentloom.activities import llm


@workflow.defn
class HelloWorld:
    @workflow.run
    async def run(self, input: str) -> str:
        result = await workflow.execute_activity(
            llm.run_llm,
            llm.LLMRequest(
                model=HAIKU_BOT.model,
                instructions=HAIKU_BOT.instructions,
                input=input,
            ),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return result
