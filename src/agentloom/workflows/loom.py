"""LoomWorkflow: a durable multi-agent pipeline.

Three agent roles are woven together in one Temporal workflow:

  1. Two researcher agents fan out in parallel, each covering a
     different angle of the topic.
  2. A writer agent weaves their notes into a short brief.
  3. A critic agent reviews the brief and produces the final cut.

Every step is a Temporal activity, so a crash at any point resumes
exactly where it left off — no lost LLM calls, no duplicate spend.

The agents themselves are declarative specs from ``agentloom.agents`` —
adding an agent to the pipeline is one spec plus one ``_run_agent`` call.
"""

import asyncio
from dataclasses import dataclass

from temporalio import workflow

from agentloom import config
from agentloom.agents import CONTRARIAN_RESEARCHER, CRITIC, RESEARCHER, WRITER, AgentSpec

# The activities module imports httpx/langfuse, which the deterministic
# workflow sandbox rejects; pass it through — the workflow only needs the
# activity reference and its request dataclass.
with workflow.unsafe.imports_passed_through():
    from agentloom.activities import llm


@dataclass
class LoomResult:
    research_notes: list[str]
    draft: str
    final: str


@workflow.defn
class LoomWorkflow:
    async def _run_agent(self, agent: AgentSpec, input: str) -> str:
        return await workflow.execute_activity(
            llm.run_llm,
            llm.LLMRequest(
                model=agent.model,
                instructions=agent.instructions,
                input=input,
            ),
            start_to_close_timeout=config.LLM_ACTIVITY_TIMEOUT,
        )

    @workflow.run
    async def run(self, topic: str) -> LoomResult:
        # 1. Researchers fan out in parallel.
        research_notes = list(
            await asyncio.gather(
                self._run_agent(RESEARCHER, topic),
                self._run_agent(CONTRARIAN_RESEARCHER, topic),
            )
        )

        # 2. Writer weaves the notes into a draft.
        draft = await self._run_agent(
            WRITER,
            f"Topic: {topic}\n\nResearch notes:\n\n" + "\n\n---\n\n".join(research_notes),
        )

        # 3. Critic reviews and returns the improved final version.
        final = await self._run_agent(CRITIC, draft)

        return LoomResult(research_notes=research_notes, draft=draft, final=final)
