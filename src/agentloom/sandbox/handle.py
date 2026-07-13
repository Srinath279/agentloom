"""Sandbox handle: the API workflows use to create and drive sandboxes.

Usage, from inside any workflow::

    from agentloom.sandbox import ProviderDetails, Sandbox

    sbx = await Sandbox.create(ProviderDetails(type="local-docker"))
    result = await sbx.execute_command("echo hello")   # .stdout/.stderr/.exit_code
    await sbx.stop()

``Sandbox.create`` starts a SandboxWorkflow child (workflow ID = sandbox ID),
then sends it a sandbox-init update. Every subsequent method is one activity
that forwards a workflow update to the sandbox — request/response semantics
without breaking determinism. Update IDs come from ``workflow.uuid4()`` so
activity retries are deduplicated by Temporal (exactly-once updates).

Snapshot/fork::

    snap = await origin.snapshot()
    fork = await Sandbox.create(provider, snapshot=snap)   # independent copy

Sharing across workflows: ``sbx.ref()`` returns an opaque string; a child or
sibling workflow calls ``Sandbox.attach(ref)`` to route commands to the same
sandbox without owning its lifecycle (only the creator can ``stop()``).
"""

import base64
import json
from enum import Enum

from temporalio import workflow
from temporalio.workflow import ParentClosePolicy

from agentloom import config

# Dotted-import form on purpose — see the note in workflow.py.
with workflow.unsafe.imports_passed_through():
    import agentloom.sandbox.types as t

_REF_VERSION = 1


class CleanupBehavior(Enum):
    """What happens to the sandbox when the creator workflow closes."""

    # Cancel the sandbox when the creator workflow closes (default).
    WITH_WORKFLOW = "with-workflow"
    # Leave the sandbox running; the caller must stop it explicitly.
    DISABLED = "disabled"


def _encode_ref(sandbox_id: str) -> str:
    data = json.dumps({"v": _REF_VERSION, "sandbox_id": sandbox_id})
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def _decode_ref(ref: str) -> str:
    try:
        padded = ref + "=" * (-len(ref) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as err:
        raise ValueError(f"sandbox: invalid ref: {err}") from err
    if data.get("v") != _REF_VERSION:
        raise ValueError(
            f"sandbox: unsupported ref version {data.get('v')} (expected {_REF_VERSION})"
        )
    sandbox_id = data.get("sandbox_id")
    if not sandbox_id:
        raise ValueError("sandbox: ref missing sandbox_id")
    return sandbox_id


def _is_gone(err: Exception) -> bool:
    """Heuristic for 'the sandbox workflow no longer exists' signal failures."""
    msg = str(err).lower()
    return "not found" in msg or "already completed" in msg or "notfound" in msg


class Sandbox:
    """Handle to a sandbox, usable only from workflow code.

    Obtain one via :meth:`create` (owning: may call :meth:`stop`) or
    :meth:`attach` (non-owning: use :meth:`request_stop` if needed at all).
    """

    def __init__(self, sandbox_id: str, _child_handle=None):
        self._sandbox_id = sandbox_id
        self._child_handle = _child_handle
        self._stopped = False

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @classmethod
    async def create(
        cls,
        provider: t.ProviderDetails,
        *,
        idle_timeout_seconds: float = 0.0,
        cleanup: CleanupBehavior = CleanupBehavior.WITH_WORKFLOW,
        snapshot: t.ProviderSnapshot | None = None,
    ) -> "Sandbox":
        """Start a sandbox as a child workflow and initialise its compute.

        idle_timeout_seconds: 0 uses the default (config.SANDBOX_IDLE_TIMEOUT_SECONDS);
        NO_IDLE_TIMEOUT (-1) disables idle auto-suspend; other negatives are rejected.
        snapshot: start from a previously taken snapshot instead of from scratch.
        """
        if idle_timeout_seconds < 0 and idle_timeout_seconds != t.NO_IDLE_TIMEOUT:
            raise ValueError(
                "sandbox: idle_timeout_seconds must be non-negative or NO_IDLE_TIMEOUT, "
                f"got {idle_timeout_seconds}"
            )

        sandbox_id = str(workflow.uuid4())
        info = workflow.info()
        child_handle = await workflow.start_child_workflow(
            t.SANDBOX_WORKFLOW_NAME,
            t.SandboxWorkflowInput(
                parent_workflow_id=info.workflow_id, parent_run_id=info.run_id
            ),
            id=sandbox_id,
            parent_close_policy=(
                ParentClosePolicy.ABANDON
                if cleanup == CleanupBehavior.DISABLED
                else ParentClosePolicy.REQUEST_CANCEL
            ),
        )

        # The child is confirmed running; init it. The activity blocks until
        # the sandbox's init update handler (compute provisioning) completes.
        await workflow.execute_activity(
            t.ACT_SEND_SANDBOX_INIT,
            t.SendSandboxInitInput(
                sandbox_id=sandbox_id,
                update_id=str(workflow.uuid4()),
                compute_provider=provider,
                idle_timeout_seconds=idle_timeout_seconds,
                snapshot=snapshot,
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
        )
        return cls(sandbox_id, _child_handle=child_handle)

    @classmethod
    def attach(cls, ref: str) -> "Sandbox":
        """Attach to an existing sandbox by opaque reference (see :meth:`ref`).

        The returned handle is non-owning: it cannot ``stop()`` and wait;
        lifecycle management belongs to the workflow that created the sandbox.
        """
        return cls(_decode_ref(ref))

    def ref(self) -> str:
        """Opaque reference for :meth:`attach` in child/sibling workflows."""
        return _encode_ref(self._sandbox_id)

    # --- operations -----------------------------------------------------------
    async def execute_command(
        self, cmd: str, *, disable_auto_resume: bool = False
    ) -> t.CommandResult:
        """Run a shell command in the sandbox.

        A suspended sandbox is transparently resumed first; pass
        ``disable_auto_resume=True`` to get a ``Suspended`` error instead.
        A non-zero exit code is returned in the result, not raised.
        """
        return await workflow.execute_activity(
            t.ACT_SEND_SANDBOX_EXECUTE_COMMAND,
            t.SendSandboxExecuteCommandInput(
                sandbox_id=self._sandbox_id,
                update_id=str(workflow.uuid4()),
                command=cmd,
                disable_auto_resume=disable_auto_resume,
            ),
            start_to_close_timeout=config.SANDBOX_COMMAND_TIMEOUT,
            result_type=t.CommandResult,
        )

    async def suspend(self) -> None:
        await workflow.execute_activity(
            t.ACT_SEND_SANDBOX_SUSPEND,
            t.SendSandboxSuspendInput(
                sandbox_id=self._sandbox_id, update_id=str(workflow.uuid4())
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
        )

    async def resume(self) -> None:
        await workflow.execute_activity(
            t.ACT_SEND_SANDBOX_RESUME,
            t.SendSandboxResumeInput(
                sandbox_id=self._sandbox_id, update_id=str(workflow.uuid4())
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
        )

    async def snapshot(self) -> t.ProviderSnapshot:
        """Capture the sandbox's filesystem state.

        Pass the result to ``Sandbox.create(..., snapshot=snap)`` to fork:
        each fork is fully independent of the origin and of other forks.
        Only valid while the sandbox is running.
        """
        return await workflow.execute_activity(
            t.ACT_SEND_SANDBOX_SNAPSHOT,
            t.SendSandboxSnapshotInput(
                sandbox_id=self._sandbox_id, update_id=str(workflow.uuid4())
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
            result_type=t.ProviderSnapshot,
        )

    async def delete_snapshot(self, snapshot: t.ProviderSnapshot) -> None:
        await workflow.execute_activity(
            t.ACT_SEND_SANDBOX_DELETE_SNAPSHOT,
            t.SendSandboxDeleteSnapshotInput(
                sandbox_id=self._sandbox_id,
                update_id=str(workflow.uuid4()),
                snapshot=snapshot,
            ),
            start_to_close_timeout=config.SANDBOX_OPERATION_TIMEOUT,
        )

    async def request_stop(self) -> None:
        """Signal the sandbox to shut down without waiting for completion."""
        try:
            await workflow.get_external_workflow_handle(self._sandbox_id).signal(
                t.SANDBOX_STOP_SIGNAL
            )
        except Exception as err:
            if _is_gone(err):
                return  # sandbox workflow already gone
            raise

    async def stop(self) -> None:
        """Signal shutdown and block until the sandbox workflow completes.

        Only available on handles returned by :meth:`create`.
        """
        if self._child_handle is None:
            raise RuntimeError(
                "sandbox: stop() requires ownership; attached handles may only request_stop()"
            )
        if self._stopped:
            return
        self._stopped = True
        try:
            await self._child_handle.signal(t.SANDBOX_STOP_SIGNAL)
        except Exception as err:
            if _is_gone(err):
                return
            raise
        await self._child_handle
