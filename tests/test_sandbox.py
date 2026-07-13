"""Sandbox module tests against Temporal's time-skipping test server.

A fake in-memory compute provider replaces real infrastructure, but
everything else is real: the SandboxWorkflow child, its update handlers,
the send-update activities, and the Sandbox handle all run through an
actual Temporal server. FakeProvider records every provider call so tests
can assert the exact lifecycle sequence.
"""

import uuid

import pytest
from temporalio import workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Workflow files must pass agentloom.sandbox through the deterministic
# sandbox (it pulls in the compute providers, which import httpx etc.).
with workflow.unsafe.imports_passed_through():
    from agentloom.sandbox import (
        NO_IDLE_TIMEOUT,
        CommandResult,
        ProviderDetails,
        Sandbox,
        SandboxWorkflow,
        compute,
        sandbox_activities,
    )
    from agentloom.sandbox.types import (
        ProviderSnapshot,
        ProviderStatus,
        SandboxPostSnapshotState,
    )

TASK_QUEUE = "test-sandbox-queue"

FAKE = ProviderDetails(type="fake")


class FakeProvider(compute.ComputeProvider):
    """In-memory provider; state is class-level because a fresh instance is
    constructed for every activity invocation."""

    calls: list[str] = []
    native_suspend = True
    _seq = 0

    def __init__(self, provider_config: dict[str, str]):
        pass

    @classmethod
    def reset(cls, native_suspend: bool = True) -> None:
        cls.calls = []
        cls.native_suspend = native_suspend
        cls._seq = 0

    @classmethod
    def _next(cls, prefix: str) -> str:
        cls._seq += 1
        return f"{prefix}-{cls._seq}"

    async def start(self, task_queue_name: str) -> ProviderStatus:
        instance = self._next("inst")
        self.calls.append(f"start:{instance}")
        return ProviderStatus(instance_id=instance)

    async def stop(self, status: ProviderStatus) -> None:
        self.calls.append(f"stop:{status.instance_id}")

    async def suspend(self, status: ProviderStatus) -> None:
        if not FakeProvider.native_suspend:
            raise compute.UnsupportedOperationError("no native suspend")
        self.calls.append(f"suspend:{status.instance_id}")

    async def resume(self, status: ProviderStatus) -> None:
        self.calls.append(f"resume:{status.instance_id}")

    async def snapshot(self, status):
        snap = self._next("snap")
        self.calls.append(f"snapshot:{status.instance_id}:{snap}")
        return SandboxPostSnapshotState.RUNNING, ProviderSnapshot(snapshot_id=snap)

    async def start_from_snapshot(self, task_queue_name, snapshot):
        instance = self._next("inst")
        self.calls.append(f"start_from_snapshot:{snapshot.snapshot_id}:{instance}")
        return ProviderStatus(instance_id=instance)

    async def delete_snapshot(self, snapshot: ProviderSnapshot) -> None:
        self.calls.append(f"delete_snapshot:{snapshot.snapshot_id}")

    async def execute_command(self, status: ProviderStatus, cmd: str) -> CommandResult:
        self.calls.append(f"exec:{status.instance_id}:{cmd}")
        return CommandResult(stdout=f"[{status.instance_id}] {cmd}")


# Guarded: the workflow sandbox re-imports this module for the parent
# workflows defined below, hitting the already-populated real registry.
if not compute.is_registered("fake"):
    compute.register("fake", FakeProvider)


@workflow.defn
class LifecycleParent:
    """create → exec → explicit suspend → exec (transparent resume) → stop"""

    @workflow.run
    async def run(self) -> list[str]:
        sbx = await Sandbox.create(FAKE, idle_timeout_seconds=NO_IDLE_TIMEOUT)
        first = await sbx.execute_command("echo one")
        await sbx.suspend()
        second = await sbx.execute_command("echo two")
        await sbx.stop()
        return [first.stdout, second.stdout]


@workflow.defn
class SnapshotForkParent:
    """snapshot an origin sandbox, fork a new sandbox from the snapshot"""

    @workflow.run
    async def run(self) -> str:
        origin = await Sandbox.create(FAKE, idle_timeout_seconds=NO_IDLE_TIMEOUT)
        await origin.execute_command("seed state")
        snap = await origin.snapshot()
        fork = await Sandbox.create(
            FAKE, idle_timeout_seconds=NO_IDLE_TIMEOUT, snapshot=snap
        )
        result = await fork.execute_command("use state")
        await fork.stop()
        await origin.stop()
        return result.stdout


@workflow.defn
class IdleAutoSuspendParent:
    """no command within the idle timeout → sandbox suspends itself"""

    @workflow.run
    async def run(self) -> str:
        sbx = await Sandbox.create(FAKE, idle_timeout_seconds=30)
        await sbx.execute_command("echo one")
        await workflow.sleep(120)  # idle timer (30s) fires in between
        result = await sbx.execute_command("echo two")  # transparent resume
        await sbx.stop()
        return result.stdout


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        yield env


async def run_parent(env, parent_workflow):
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[parent_workflow, SandboxWorkflow],
        activities=sandbox_activities(env.client),
    ):
        return await env.client.execute_workflow(
            parent_workflow.run,
            id=f"test-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )


async def test_lifecycle_native_suspend_and_auto_resume(env):
    FakeProvider.reset()

    result = await run_parent(env, LifecycleParent)

    assert result == ["[inst-1] echo one", "[inst-1] echo two"]
    assert FakeProvider.calls == [
        "start:inst-1",
        "exec:inst-1:echo one",
        "suspend:inst-1",
        "resume:inst-1",  # transparent resume before the second command
        "exec:inst-1:echo two",
        "stop:inst-1",
    ]


async def test_suspend_falls_back_to_snapshot_for_unsupported_providers(env):
    FakeProvider.reset(native_suspend=False)

    result = await run_parent(env, LifecycleParent)

    # Resume restarts from the internal snapshot on a fresh instance, and the
    # internal snapshot is deleted afterwards.
    assert result == ["[inst-1] echo one", "[inst-3] echo two"]
    assert FakeProvider.calls == [
        "start:inst-1",
        "exec:inst-1:echo one",
        "snapshot:inst-1:snap-2",  # suspend fallback: snapshot…
        "stop:inst-1",  # …then stop the instance
        "start_from_snapshot:snap-2:inst-3",
        "delete_snapshot:snap-2",  # internal snapshot cleaned up on resume
        "exec:inst-3:echo two",
        "stop:inst-3",
    ]


async def test_snapshot_fork_starts_independent_sandbox(env):
    FakeProvider.reset()

    result = await run_parent(env, SnapshotForkParent)

    assert result == "[inst-3] use state"
    assert FakeProvider.calls == [
        "start:inst-1",
        "exec:inst-1:seed state",
        "snapshot:inst-1:snap-2",
        "start_from_snapshot:snap-2:inst-3",  # fork from user-owned snapshot
        "exec:inst-3:use state",
        "stop:inst-3",
        "stop:inst-1",  # origin still running; user snapshot never auto-deleted
    ]


async def test_idle_timeout_auto_suspends_sandbox(env):
    FakeProvider.reset()

    result = await run_parent(env, IdleAutoSuspendParent)

    assert result == "[inst-1] echo two"
    assert FakeProvider.calls == [
        "start:inst-1",
        "exec:inst-1:echo one",
        "suspend:inst-1",  # idle timer fired, nobody asked
        "resume:inst-1",
        "exec:inst-1:echo two",
        "stop:inst-1",
    ]
