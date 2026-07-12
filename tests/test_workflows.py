"""Workflow tests against Temporal's time-skipping test server.

WorkflowEnvironment.start_time_skipping() spins up a real (local, in-process)
Temporal test server, so the actual workflow code runs through the actual
server — but timers skip instantly and no LLM is called: the `create`
activity is replaced with a scripted fake registered under the same name.
"""

import uuid

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from activities.openai_responses import LLMResponsesRequest
from workflows.hello_world_workflow import HelloWorld
from workflows.loom_workflow import LoomWorkflow

TASK_QUEUE = "test-queue"


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        yield env


async def test_hello_world_returns_activity_result(env):
    @activity.defn(name="create")
    async def fake_create(request: LLMResponsesRequest) -> str:
        return f"haiku about: {request.input}"

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[HelloWorld], activities=[fake_create]
    ):
        result = await env.client.execute_workflow(
            HelloWorld.run,
            "recursion",
            id=f"test-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )

    assert result == "haiku about: recursion"


async def test_loom_workflow_weaves_all_agents(env):
    calls: list[LLMResponsesRequest] = []

    @activity.defn(name="create")
    async def fake_create(request: LLMResponsesRequest) -> str:
        calls.append(request)
        if "researcher" in request.instructions:
            return f"notes({request.instructions[:14]})"
        if "writer" in request.instructions:
            return "the draft"
        if "editor" in request.instructions:
            return "the final brief"
        raise ApplicationError(f"unexpected agent: {request.instructions}")

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[LoomWorkflow], activities=[fake_create]
    ):
        result = await env.client.execute_workflow(
            LoomWorkflow.run,
            "temporal workflows",
            id=f"test-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )

    # 2 researchers + 1 writer + 1 critic
    assert len(calls) == 4
    assert len(result.research_notes) == 2
    assert result.draft == "the draft"
    assert result.final == "the final brief"
    # writer must receive both researchers' notes
    writer_call = next(c for c in calls if "writer" in c.instructions)
    for note in result.research_notes:
        assert note in writer_call.input


async def test_hello_world_fails_after_activity_retries_exhausted(env):
    @activity.defn(name="create")
    async def always_fails(request: LLMResponsesRequest) -> str:
        raise ApplicationError("LLM down", non_retryable=True)

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[HelloWorld], activities=[always_fails]
    ):
        with pytest.raises(WorkflowFailureError):
            await env.client.execute_workflow(
                HelloWorld.run,
                "boom",
                id=f"test-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
