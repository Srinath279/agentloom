"""LoomWorkflow: a durable multi-agent pipeline.

Three agents are woven together in one Temporal workflow:

  1. Two researcher agents fan out in parallel, each covering a
     different angle of the topic.
  2. A writer agent weaves their notes into a short brief.
  3. A critic agent reviews the brief and produces the final cut.

Every step is a Temporal activity, so a crash at any point resumes
exactly where it left off — no lost LLM calls, no duplicate spend.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

from activities import openai_responses

MODEL = "gpt-4o-mini"
LLM_TIMEOUT = timedelta(seconds=60)


@dataclass
class LoomResult:
    research_notes: list[str]
    draft: str
    final: str


@workflow.defn
class LoomWorkflow:
    async def _agent(self, instructions: str, input: str) -> str:
        result = await workflow.execute_activity(
            openai_responses.create,
            openai_responses.OpenAIResponsesRequest(
                model=MODEL,
                instructions=instructions,
                input=input,
            ),
            start_to_close_timeout=LLM_TIMEOUT,
        )
        return result.output_text

    @workflow.run
    async def run(self, topic: str) -> LoomResult:
        # 1. Researchers fan out in parallel.
        research_notes = list(
            await asyncio.gather(
                self._agent(
                    "You are a researcher. List 3-5 key facts about the topic. "
                    "Be concrete and cite well-known sources where possible.",
                    topic,
                ),
                self._agent(
                    "You are a contrarian researcher. List 3-5 common "
                    "misconceptions or open questions about the topic.",
                    topic,
                ),
            )
        )

        # 2. Writer weaves the notes into a draft.
        draft = await self._agent(
            "You are a technical writer. Weave the research notes into a "
            "clear, engaging brief of at most 200 words.",
            f"Topic: {topic}\n\nResearch notes:\n\n" + "\n\n---\n\n".join(research_notes),
        )

        # 3. Critic reviews and returns the improved final version.
        final = await self._agent(
            "You are an exacting editor. Improve the draft for accuracy, "
            "clarity, and flow. Return only the revised text.",
            draft,
        )

        return LoomResult(research_notes=research_notes, draft=draft, final=final)
