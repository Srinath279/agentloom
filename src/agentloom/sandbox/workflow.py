"""SandboxWorkflow: the long-lived child workflow behind every sandbox.

One workflow execution == one sandbox; its workflow ID is the sandbox ID so
parent workflows can address it directly. The parent drives it through
updates (init, execute-command, suspend, resume, snapshot, delete-snapshot),
a stop signal, and a state query — see :mod:`agentloom.sandbox.handle` for
the ergonomic wrapper.

Lifecycle behaviours ported from the Go harness:
  - after each command an idle timer starts; if no command arrives within
    the idle timeout the sandbox is auto-suspended (opt out with
    NO_IDLE_TIMEOUT);
  - a suspended sandbox is transparently resumed by the next command
    (unless the command disables auto-resume);
  - providers without native suspend fall back to snapshot+stop, resuming
    later via start-from-snapshot;
  - on stop (signal or parent-close cancellation) the compute resource is
    torn down and any internal suspend snapshot deleted.
"""

import asyncio

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

from agentloom import config

# Dotted-import form on purpose: `from agentloom.sandbox import compute`
# would bypass the passthrough (the already-sandboxed parent package makes
# CPython import the submodule internally, skipping Temporal's importer),
# yielding a sandboxed copy with an empty provider registry.
with workflow.unsafe.imports_passed_through():
    import agentloom.sandbox.compute as compute
    import agentloom.sandbox.types as t


class _Lifecycle:
    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    FAILED = "failed"
    DELETED = "deleted"


@workflow.defn(name=t.SANDBOX_WORKFLOW_NAME)
class SandboxWorkflow:
    def __init__(self) -> None:
        self._lifecycle: str = _Lifecycle.PENDING
        self._cancel_requested = False
        self._provider: t.ProviderDetails | None = None
        self._status: t.ProviderStatus | None = None
        self._idle_timeout_seconds: float = 0.0
        self._idle_timer: asyncio.Task | None = None
        # Set when suspended via snapshot+stop (providers without native
        # suspend) or when the provider suspended the sandbox as part of a
        # user Snapshot call. Non-None means resume restarts from snapshot.
        self._suspend_snapshot: t.ProviderSnapshot | None = None
        # True when the suspend snapshot came from a user Snapshot call: the
        # user holds a reference, so never auto-delete it on resume/cleanup.
        self._suspend_snapshot_user_owned = False

    # --- main -------------------------------------------------------------
    @workflow.run
    async def run(self, input: t.SandboxWorkflowInput) -> None:
        await workflow.wait_condition(lambda: self._lifecycle != _Lifecycle.PENDING)
        if self._lifecycle == _Lifecycle.FAILED:
            return

        workflow.logger.info(
            "sandbox initialised (parent %s, provider %s)",
            input.parent_workflow_id,
            self._provider.type if self._provider else "?",
        )

        # Block until a stop signal arrives, the parent-close policy cancels
        # us, or the sandbox was deleted as a snapshot side-effect. Catching
        # the cancellation lets cleanup activities still run, and reports the
        # workflow as Completed rather than Failed.
        try:
            await workflow.wait_condition(lambda: self._cancel_requested)
        except asyncio.CancelledError:
            self._cancel_requested = True
        self._cancel_idle_timer()

        if self._provider is None or self._status is None:
            return
        if self._suspend_snapshot is not None and not self._suspend_snapshot_user_owned:
            # Internal suspend snapshot: the compute resource was already
            # stopped by the snapshot+stop fallback; delete the orphan.
            await workflow.execute_activity(
                t.ACT_DELETE_SNAPSHOT,
                t.DeleteSnapshotInput(provider=self._provider, snapshot=self._suspend_snapshot),
                start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            )
        else:
            # No suspend snapshot, or a user-owned one (never auto-deleted).
            # The compute resource may still be running or paused: stop it.
            await workflow.execute_activity(
                t.ACT_STOP_SANDBOX,
                t.StopSandboxInput(provider=self._provider, status=self._status),
                start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            )

    # --- signals / queries ---------------------------------------------------
    @workflow.signal(name=t.SANDBOX_STOP_SIGNAL)
    def stop(self) -> None:
        self._cancel_requested = True

    @workflow.query(name=t.SANDBOX_STATE_QUERY)
    def state(self) -> t.SandboxState:
        return t.SandboxState(
            lifecycle=self._public_lifecycle(),
            compute_provider=self._provider,
            status=self._status,
            idle_timeout_seconds=self._idle_timeout_seconds,
        )

    def _public_lifecycle(self) -> t.SandboxLifecycle:
        if self._lifecycle == _Lifecycle.SUSPENDED and self._suspend_snapshot is not None:
            return t.SandboxLifecycle.SUSPENDED_WITH_SNAPSHOT
        return t.SandboxLifecycle(self._lifecycle)

    # --- init -----------------------------------------------------------------
    @workflow.update(name=t.SANDBOX_INIT_UPDATE)
    async def sandbox_init(self, inp: t.SandboxInitInput) -> None:
        activity_name = t.ACT_START_SANDBOX
        arg: object = t.StartSandboxInput(
            provider=inp.compute_provider, task_queue_name=self._task_queue_name()
        )
        if inp.snapshot is not None:
            activity_name = t.ACT_START_SANDBOX_FROM_SNAPSHOT
            arg = t.StartSandboxFromSnapshotInput(
                provider=inp.compute_provider,
                task_queue_name=self._task_queue_name(),
                snapshot=inp.snapshot,
            )
        try:
            out: t.StartSandboxOutput = await workflow.execute_activity(
                activity_name,
                arg,
                start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
                result_type=t.StartSandboxOutput,
            )
        except ActivityError:
            self._lifecycle = _Lifecycle.FAILED
            raise
        self._status = out.status
        self._provider = inp.compute_provider
        self._idle_timeout_seconds = inp.idle_timeout_seconds
        self._lifecycle = _Lifecycle.RUNNING

    @sandbox_init.validator
    def validate_init(self, inp: t.SandboxInitInput) -> None:
        if self._lifecycle != _Lifecycle.PENDING:
            raise ApplicationError("sandbox already initialized", type="AlreadyInitialized")
        if not compute.is_registered(inp.compute_provider.type):
            raise ApplicationError("unknown compute provider type", type="InvalidArgument")

    # --- execute command ---------------------------------------------------------
    @workflow.update(name=t.SANDBOX_EXECUTE_COMMAND_UPDATE)
    async def sandbox_execute_command(
        self, inp: t.SandboxExecuteCommandInput
    ) -> t.CommandResult:
        # Cancel any in-flight idle timer from the previous command.
        self._cancel_idle_timer()

        if self._lifecycle == _Lifecycle.SUSPENDED:
            await self._resume_impl()

        result: t.CommandResult = await workflow.execute_activity(
            t.ACT_EXECUTE_COMMAND,
            t.ExecuteCommandInput(
                provider=self._provider, status=self._status, command=inp.command
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            result_type=t.CommandResult,
        )

        if self._idle_timeout_seconds != t.NO_IDLE_TIMEOUT:
            self._idle_timer = asyncio.create_task(self._idle_auto_suspend())
        return result

    @sandbox_execute_command.validator
    def validate_execute_command(self, inp: t.SandboxExecuteCommandInput) -> None:
        self._require_initialized()
        if self._lifecycle == _Lifecycle.SUSPENDED and inp.disable_auto_resume:
            raise ApplicationError("sandbox is suspended", type="Suspended")

    async def _idle_auto_suspend(self) -> None:
        try:
            await workflow.sleep(self._effective_idle_timeout())
        except asyncio.CancelledError:
            return  # cancelled by the next command or workflow stop
        if self._lifecycle != _Lifecycle.SUSPENDED and not self._cancel_requested:
            try:
                await self._suspend_impl()
            except Exception as err:
                workflow.logger.error(
                    "sandbox: idle auto-suspend failed; sandbox continues running: %s", err
                )

    # --- suspend / resume ------------------------------------------------------
    @workflow.update(name=t.SANDBOX_SUSPEND_UPDATE)
    async def sandbox_suspend(self) -> None:
        self._cancel_idle_timer()
        await self._suspend_impl()

    @sandbox_suspend.validator
    def validate_suspend(self) -> None:
        self._require_initialized()
        if self._lifecycle == _Lifecycle.SUSPENDED:
            raise ApplicationError("sandbox already suspended", type="AlreadySuspended")

    async def _suspend_impl(self) -> None:
        try:
            await workflow.execute_activity(
                t.ACT_SUSPEND_SANDBOX,
                t.SuspendSandboxInput(provider=self._provider, status=self._status),
                start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            )
        except ActivityError as err:
            if (
                isinstance(err.cause, ApplicationError)
                and err.cause.type == t.ERR_UNSUPPORTED
            ):
                await self._suspend_via_snapshot()
                return
            raise
        self._lifecycle = _Lifecycle.SUSPENDED

    async def _suspend_via_snapshot(self) -> None:
        """Fallback for providers without native suspend: snapshot then stop."""
        out: t.SnapshotSandboxOutput = await workflow.execute_activity(
            t.ACT_SNAPSHOT_SANDBOX,
            t.SnapshotSandboxInput(provider=self._provider, status=self._status),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            result_type=t.SnapshotSandboxOutput,
        )
        # Some providers already pause the sandbox as part of snapshotting;
        # only stop it when it is still running.
        if out.sandbox_state == t.SandboxPostSnapshotState.RUNNING:
            await workflow.execute_activity(
                t.ACT_STOP_SANDBOX,
                t.StopSandboxInput(provider=self._provider, status=self._status),
                start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            )
        self._suspend_snapshot = out.snapshot
        self._suspend_snapshot_user_owned = False
        self._lifecycle = _Lifecycle.SUSPENDED

    @workflow.update(name=t.SANDBOX_RESUME_UPDATE)
    async def sandbox_resume(self) -> None:
        await self._resume_impl()

    @sandbox_resume.validator
    def validate_resume(self) -> None:
        self._require_initialized()
        if self._lifecycle != _Lifecycle.SUSPENDED:
            raise ApplicationError("sandbox not suspended", type="NotSuspended")

    async def _resume_impl(self) -> None:
        if self._suspend_snapshot is None:
            await workflow.execute_activity(
                t.ACT_RESUME_SANDBOX,
                t.ResumeSandboxInput(provider=self._provider, status=self._status),
                start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            )
            self._lifecycle = _Lifecycle.RUNNING
            return

        out: t.StartSandboxOutput = await workflow.execute_activity(
            t.ACT_START_SANDBOX_FROM_SNAPSHOT,
            t.StartSandboxFromSnapshotInput(
                provider=self._provider,
                task_queue_name=self._task_queue_name(),
                snapshot=self._suspend_snapshot,
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            result_type=t.StartSandboxOutput,
        )
        self._status = out.status
        old_snapshot = self._suspend_snapshot
        was_user_owned = self._suspend_snapshot_user_owned
        self._suspend_snapshot = None
        self._suspend_snapshot_user_owned = False
        self._lifecycle = _Lifecycle.RUNNING

        # Only delete internally created suspend snapshots. User-owned ones
        # (from an explicit Snapshot call) are the caller's responsibility;
        # deleting them would invalidate forks the caller intends to create.
        if not was_user_owned:
            try:
                await workflow.execute_activity(
                    t.ACT_DELETE_SNAPSHOT,
                    t.DeleteSnapshotInput(provider=self._provider, snapshot=old_snapshot),
                    start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
                )
            except ActivityError as err:
                workflow.logger.error(
                    "sandbox: failed to delete suspend snapshot %s after resume: %s",
                    old_snapshot.snapshot_id,
                    err,
                )

    # --- snapshot -----------------------------------------------------------------
    @workflow.update(name=t.SANDBOX_SNAPSHOT_UPDATE)
    async def sandbox_snapshot(self) -> t.ProviderSnapshot:
        out: t.SnapshotSandboxOutput = await workflow.execute_activity(
            t.ACT_SNAPSHOT_SANDBOX,
            t.SnapshotSandboxInput(provider=self._provider, status=self._status),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            result_type=t.SnapshotSandboxOutput,
        )
        self._cancel_idle_timer()

        if out.sandbox_state == t.SandboxPostSnapshotState.SUSPENDED:
            # Provider paused the sandbox while snapshotting: resume must
            # restart from this snapshot. User-owned — never auto-delete it.
            self._lifecycle = _Lifecycle.SUSPENDED
            self._suspend_snapshot = out.snapshot
            self._suspend_snapshot_user_owned = True
        elif out.sandbox_state == t.SandboxPostSnapshotState.DELETED:
            self._lifecycle = _Lifecycle.DELETED
            self._status = None  # resource is gone; skip stop in cleanup
            self._cancel_requested = True
        return out.snapshot

    @sandbox_snapshot.validator
    def validate_snapshot(self) -> None:
        self._require_initialized()
        if self._lifecycle == _Lifecycle.SUSPENDED:
            raise ApplicationError("sandbox is currently suspended", type="InvalidSandboxState")

    @workflow.update(name=t.SANDBOX_DELETE_SNAPSHOT_UPDATE)
    async def sandbox_delete_snapshot(self, snapshot: t.ProviderSnapshot) -> None:
        if (
            self._suspend_snapshot is not None
            and self._suspend_snapshot.snapshot_id == snapshot.snapshot_id
        ):
            raise ApplicationError(
                "snapshot is currently in use by this sandbox", type="SnapshotInUse"
            )
        await workflow.execute_activity(
            t.ACT_DELETE_SNAPSHOT,
            t.DeleteSnapshotInput(provider=self._provider, snapshot=snapshot),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
        )

    @sandbox_delete_snapshot.validator
    def validate_delete_snapshot(self, snapshot: t.ProviderSnapshot) -> None:
        self._require_initialized()
        if snapshot is None or not snapshot.snapshot_id:
            raise ApplicationError("invalid snapshot reference", type="InvalidArgument")

    # --- helpers --------------------------------------------------------------------
    def _require_initialized(self) -> None:
        if self._lifecycle in (_Lifecycle.PENDING, _Lifecycle.FAILED, _Lifecycle.DELETED):
            raise ApplicationError("sandbox not initialized", type="NotInitialized")

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _effective_idle_timeout(self) -> float:
        if self._idle_timeout_seconds > 0:
            return self._idle_timeout_seconds
        return config.SANDBOX_IDLE_TIMEOUT_SECONDS

    def _task_queue_name(self) -> str:
        # Providers that run a Temporal worker inside the sandbox point it
        # at a task queue derived from the sandbox ID.
        return f"sandbox-{workflow.info().workflow_id}"
