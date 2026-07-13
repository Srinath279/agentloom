"""Sandbox activities: provider operations and update forwarding.

Two groups, mirroring the Go harness:

- Lifecycle activities (start_sandbox, execute_command, …) look up the
  compute provider from serialized ProviderDetails and run one provider
  operation. They execute on the SandboxWorkflow side.

- Send* activities forward a request from a *parent* workflow to a
  SandboxWorkflow as a Temporal workflow update, via client.execute_update.
  Running the update inside an activity gives the parent request/response
  semantics (it blocks until the sandbox has processed the update) without
  breaking workflow determinism. The stable update_id (a workflow.uuid4()
  from the parent) makes retries idempotent: Temporal deduplicates updates
  by ID, so each is applied exactly once.

Use :func:`sandbox_activities` to build the full registration list for a
worker.
"""

from temporalio import activity
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from agentloom.sandbox import compute
from agentloom.sandbox import types as t


def _lookup(details: t.ProviderDetails) -> compute.ComputeProvider:
    try:
        return compute.lookup(details)
    except (KeyError, ValueError) as err:
        raise ApplicationError(str(err), type="ProviderConfigError", non_retryable=True) from err


def _unsupported(err: compute.UnsupportedOperationError) -> ApplicationError:
    # Non-retryable so the workflow immediately falls back (e.g. suspend via
    # snapshot) instead of retrying an operation the provider will never support.
    return ApplicationError(
        str(err) or "operation not supported by provider",
        type=t.ERR_UNSUPPORTED,
        non_retryable=True,
    )


# --- Lifecycle activities ----------------------------------------------------
@activity.defn(name=t.ACT_START_SANDBOX)
async def start_sandbox(input: t.StartSandboxInput) -> t.StartSandboxOutput:
    provider = _lookup(input.provider)
    try:
        status = await provider.start(input.task_queue_name)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err
    return t.StartSandboxOutput(status=status)


@activity.defn(name=t.ACT_STOP_SANDBOX)
async def stop_sandbox(input: t.StopSandboxInput) -> None:
    provider = _lookup(input.provider)
    try:
        await provider.stop(input.status)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err


@activity.defn(name=t.ACT_SUSPEND_SANDBOX)
async def suspend_sandbox(input: t.SuspendSandboxInput) -> None:
    provider = _lookup(input.provider)
    try:
        await provider.suspend(input.status)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err


@activity.defn(name=t.ACT_RESUME_SANDBOX)
async def resume_sandbox(input: t.ResumeSandboxInput) -> None:
    provider = _lookup(input.provider)
    try:
        await provider.resume(input.status)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err


@activity.defn(name=t.ACT_SNAPSHOT_SANDBOX)
async def snapshot_sandbox(input: t.SnapshotSandboxInput) -> t.SnapshotSandboxOutput:
    provider = _lookup(input.provider)
    try:
        state, snapshot = await provider.snapshot(input.status)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err
    return t.SnapshotSandboxOutput(sandbox_state=state, snapshot=snapshot)


@activity.defn(name=t.ACT_START_SANDBOX_FROM_SNAPSHOT)
async def start_sandbox_from_snapshot(
    input: t.StartSandboxFromSnapshotInput,
) -> t.StartSandboxOutput:
    provider = _lookup(input.provider)
    try:
        status = await provider.start_from_snapshot(input.task_queue_name, input.snapshot)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err
    return t.StartSandboxOutput(status=status)


@activity.defn(name=t.ACT_DELETE_SNAPSHOT)
async def delete_snapshot(input: t.DeleteSnapshotInput) -> None:
    provider = _lookup(input.provider)
    try:
        await provider.delete_snapshot(input.snapshot)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err


@activity.defn(name=t.ACT_EXECUTE_COMMAND)
async def execute_command(input: t.ExecuteCommandInput) -> t.CommandResult:
    provider = _lookup(input.provider)
    try:
        return await provider.execute_command(input.status, input.command)
    except compute.UnsupportedOperationError as err:
        raise _unsupported(err) from err


LIFECYCLE_ACTIVITIES = [
    start_sandbox,
    stop_sandbox,
    suspend_sandbox,
    resume_sandbox,
    snapshot_sandbox,
    start_sandbox_from_snapshot,
    delete_snapshot,
    execute_command,
]


# --- Send-update activities ----------------------------------------------------
class SandboxClientActivities:
    """Activities that forward workflow updates to a SandboxWorkflow.

    Holds a Temporal client, so instances are built at worker startup via
    :func:`sandbox_activities` rather than listed statically.
    """

    _NO_ARG = object()

    def __init__(self, client: Client):
        self._client = client

    async def _execute_update(self, sandbox_id, update_id, update, arg=_NO_ARG, result_type=None):
        handle = self._client.get_workflow_handle(sandbox_id)
        try:
            if arg is self._NO_ARG:
                return await handle.execute_update(update, id=update_id, result_type=result_type)
            return await handle.execute_update(
                update, arg, id=update_id, result_type=result_type
            )
        except WorkflowUpdateFailedError as err:
            # Make update failures non-retryable at the activity level: the
            # update was delivered and rejected/failed, so retrying the
            # activity would just replay the same outcome. Domain error types
            # (AlreadySuspended, NotInitialized, …) are preserved.
            cause = err.cause
            if isinstance(cause, ApplicationError):
                raise ApplicationError(
                    cause.message, type=cause.type, non_retryable=True
                ) from err
            raise ApplicationError(str(err), type="UpdateWorkflowFailure", non_retryable=True) from err
        except RPCError as err:
            if err.status == RPCStatusCode.NOT_FOUND:
                raise ApplicationError(
                    "sandbox not found", type="SandboxNotFound", non_retryable=True
                ) from err
            raise

    @activity.defn(name=t.ACT_SEND_SANDBOX_INIT)
    async def send_sandbox_init(self, input: t.SendSandboxInitInput) -> None:
        await self._execute_update(
            input.sandbox_id,
            input.update_id,
            t.SANDBOX_INIT_UPDATE,
            t.SandboxInitInput(
                compute_provider=input.compute_provider,
                idle_timeout_seconds=input.idle_timeout_seconds,
                snapshot=input.snapshot,
            ),
        )

    @activity.defn(name=t.ACT_SEND_SANDBOX_EXECUTE_COMMAND)
    async def send_sandbox_execute_command(
        self, input: t.SendSandboxExecuteCommandInput
    ) -> t.CommandResult:
        return await self._execute_update(
            input.sandbox_id,
            input.update_id,
            t.SANDBOX_EXECUTE_COMMAND_UPDATE,
            t.SandboxExecuteCommandInput(
                command=input.command, disable_auto_resume=input.disable_auto_resume
            ),
            result_type=t.CommandResult,
        )

    @activity.defn(name=t.ACT_SEND_SANDBOX_SUSPEND)
    async def send_sandbox_suspend(self, input: t.SendSandboxSuspendInput) -> None:
        await self._execute_update(input.sandbox_id, input.update_id, t.SANDBOX_SUSPEND_UPDATE)

    @activity.defn(name=t.ACT_SEND_SANDBOX_RESUME)
    async def send_sandbox_resume(self, input: t.SendSandboxResumeInput) -> None:
        await self._execute_update(input.sandbox_id, input.update_id, t.SANDBOX_RESUME_UPDATE)

    @activity.defn(name=t.ACT_SEND_SANDBOX_SNAPSHOT)
    async def send_sandbox_snapshot(
        self, input: t.SendSandboxSnapshotInput
    ) -> t.ProviderSnapshot:
        return await self._execute_update(
            input.sandbox_id,
            input.update_id,
            t.SANDBOX_SNAPSHOT_UPDATE,
            result_type=t.ProviderSnapshot,
        )

    @activity.defn(name=t.ACT_SEND_SANDBOX_DELETE_SNAPSHOT)
    async def send_sandbox_delete_snapshot(
        self, input: t.SendSandboxDeleteSnapshotInput
    ) -> None:
        await self._execute_update(
            input.sandbox_id,
            input.update_id,
            t.SANDBOX_DELETE_SNAPSHOT_UPDATE,
            input.snapshot,
        )


def sandbox_activities(client: Client) -> list:
    """All sandbox activities for worker registration.

    Combines the module-level lifecycle activities with the client-bound
    send activities. Call once at worker startup, after connecting the client.
    """
    sender = SandboxClientActivities(client)
    return [
        *LIFECYCLE_ACTIVITIES,
        sender.send_sandbox_init,
        sender.send_sandbox_execute_command,
        sender.send_sandbox_suspend,
        sender.send_sandbox_resume,
        sender.send_sandbox_snapshot,
        sender.send_sandbox_delete_snapshot,
    ]
