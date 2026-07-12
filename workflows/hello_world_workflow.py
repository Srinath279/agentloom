"""Single-agent starter workflow: one LLM call, in haiku form."""

from datetime import timedelta

from temporalio import workflow

from activities import openai_responses


@workflow.defn
class HelloWorld:
    @workflow.run
    async def run(self, input: str) -> str:
        result = await workflow.execute_activity(
            openai_responses.create,
            openai_responses.OpenAIResponsesRequest(
                model="gpt-4o-mini",
                instructions="You only respond in haikus.",
                input=input,
            ),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return result.output_text
