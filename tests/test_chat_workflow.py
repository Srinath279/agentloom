"""ChatWorkflow tests against Temporal's time-skipping test server.

The `run_llm` activity is replaced with a scripted fake, so these verify the
durable-conversation mechanics: signals append to history, replies land in
the transcript, the query exposes state, and end_chat completes the run.
"""

import asyncio
import uuid

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentloom.activities.llm import LLMRequest
from agentloom.workflows import ChatWorkflow

TASK_QUEUE = "test-queue"


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        yield env


async def test_chat_roundtrip_and_end(env):
    prompts: list[LLMRequest] = []

    @activity.defn(name="run_llm")
    async def fake_run_llm(request: LLMRequest) -> str:
        prompts.append(request)
        return f"echo: {request.input.splitlines()[-2]}"  # last user line

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[ChatWorkflow], activities=[fake_run_llm]
    ):
        handle = await env.client.start_workflow(
            ChatWorkflow.run,
            None,
            id=f"chat-test-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )

        await handle.signal(ChatWorkflow.user_message, "hello there")
        # Wait until the assistant reply shows up in the queried transcript.
        for _ in range(50):
            state = await handle.query(ChatWorkflow.get_history)
            if len(state.messages) == 2 and not state.responding:
                break
            await asyncio.sleep(0.1)

        assert [m.role for m in state.messages] == ["user", "assistant"]
        assert state.messages[0].content == "hello there"
        assert state.messages[1].content == "echo: User: hello there"

        # Second turn: transcript context is included in the prompt.
        await handle.signal(ChatWorkflow.user_message, "second message")
        for _ in range(50):
            state = await handle.query(ChatWorkflow.get_history)
            if len(state.messages) == 4:
                break
            await asyncio.sleep(0.1)
        assert "hello there" in prompts[-1].input
        assert prompts[-1].input.rstrip().endswith("Assistant:")

        await handle.signal(ChatWorkflow.end_chat)
        result = await handle.result()

    assert result.ended is True
    assert len(result.messages) == 4


async def test_chat_blank_messages_ignored(env):
    @activity.defn(name="run_llm")
    async def fake_run_llm(request: LLMRequest) -> str:
        return "reply"

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[ChatWorkflow], activities=[fake_run_llm]
    ):
        handle = await env.client.start_workflow(
            ChatWorkflow.run,
            None,
            id=f"chat-test-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
        await handle.signal(ChatWorkflow.user_message, "   ")
        await handle.signal(ChatWorkflow.end_chat)
        result = await handle.result()

    assert result.messages == []
