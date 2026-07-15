"""task_fn wiring: agent-evals -> Temporal -> LoomWorkflow -> canonical Trace.

Contract: invoke_loom(case_input) -> Trace. Each eval execution:
1. opens ONE Langfuse trace (session_id = the workflow ID, same convention
   as agentloom.tracing) so eval scores attach to a real trace and sit in
   the same session as the four agent generations;
2. runs the real LoomWorkflow on the agentloom task queue (the agentloom
   worker must be running);
3. maps the pipeline stages onto canonical ToolCalls so trajectory
   evaluators (tool_called, tool_selection, steps_efficiency) grade the
   run shape, not just the text.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from agent_evals.core.schemas import ToolCall, Trace
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from agentloom import config
from agentloom.workflows import LoomWorkflow

import evals.custom_evaluators  # noqa: F401  (registers word_count_range)

STAGES = ["research_facts", "research_misconceptions", "write_draft", "critique"]


async def _run_workflow(topic: str, workflow_id: str):
    client = await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
    )
    return await client.execute_workflow(
        LoomWorkflow.run,
        topic,
        id=workflow_id,
        task_queue=config.TASK_QUEUE,
    )


def _snippet(text: str, limit: int = 200) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def invoke_loom(case_input: dict[str, Any]) -> Trace:
    topic = case_input["topic"]
    workflow_id = f"eval-loom-{uuid.uuid4().hex[:10]}"

    from langfuse import get_client, propagate_attributes

    langfuse = get_client()
    started = time.monotonic()
    # same conventions as agentloom.tracing: session_id = workflow ID, so this
    # eval trace sits in the same Langfuse session as the agent generations
    with propagate_attributes(
        tags=["eval", "agentloom"], session_id=workflow_id, trace_name="LoomEval"
    ):
        with langfuse.start_as_current_observation(
            name="loom-eval-run", as_type="span", input=case_input
        ) as span:
            langfuse_trace_id = langfuse.get_current_trace_id()
            result = asyncio.run(_run_workflow(topic, workflow_id))
            latency_ms = (time.monotonic() - started) * 1000
            span.update(output={"final": result.final})
    langfuse.flush()

    stage_outputs = dict(zip(STAGES, [*result.research_notes, result.draft, result.final]))
    tool_calls = [
        ToolCall(name=stage, arguments={"topic": topic}, result=_snippet(output))
        for stage, output in stage_outputs.items()
    ]

    return Trace(
        trace_id="",  # runner assigns the deterministic (run, case, repeat) ID
        agent="loom-brief",
        input=case_input,
        output={"final": result.final, "draft": result.draft,
                "research_notes": result.research_notes},
        tool_calls=tool_calls,
        steps=len(STAGES),
        latency_ms=latency_ms,
        cost_usd=0.0,  # local Ollama; real cost lands when OpenRouter is used
        metadata={
            "workflow_id": workflow_id,
            "source_trace_id": langfuse_trace_id,  # scores attach to this trace
        },
    )
