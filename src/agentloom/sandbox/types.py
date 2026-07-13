"""Shared data types and wire names for the sandbox module.

Python port of the SDK types from
https://github.com/temporal-community/sandbox-orchestration-harness — the
compute-provider value objects, the sandbox workflow's update/signal/query
names, and the activity request/response dataclasses.

Stdlib-only on purpose: this module is imported from workflow code, which
runs inside Temporal's deterministic sandbox.
"""

from dataclasses import dataclass, field
from enum import Enum, IntEnum

# --- Wire names ---------------------------------------------------------------
# Kept identical to the Go SDK so the two implementations are interoperable
# against the same Temporal server.
SANDBOX_WORKFLOW_NAME = "SandboxWorkflow"
SANDBOX_INIT_UPDATE = "sandbox-init"
SANDBOX_EXECUTE_COMMAND_UPDATE = "sandbox-execute-command"
SANDBOX_SUSPEND_UPDATE = "sandbox-suspend"
SANDBOX_RESUME_UPDATE = "sandbox-resume"
SANDBOX_SNAPSHOT_UPDATE = "sandbox-snapshot"
SANDBOX_DELETE_SNAPSHOT_UPDATE = "sandbox-delete-snapshot"
SANDBOX_STOP_SIGNAL = "sandbox-stop"
SANDBOX_STATE_QUERY = "sandbox-state"

# Activity names. The lifecycle activities run provider operations; the
# send_* activities forward updates from a parent workflow to a
# SandboxWorkflow via client.execute_update.
ACT_START_SANDBOX = "start_sandbox"
ACT_STOP_SANDBOX = "stop_sandbox"
ACT_SUSPEND_SANDBOX = "suspend_sandbox"
ACT_RESUME_SANDBOX = "resume_sandbox"
ACT_SNAPSHOT_SANDBOX = "snapshot_sandbox"
ACT_START_SANDBOX_FROM_SNAPSHOT = "start_sandbox_from_snapshot"
ACT_DELETE_SNAPSHOT = "delete_snapshot"
ACT_EXECUTE_COMMAND = "execute_command"
ACT_SEND_SANDBOX_INIT = "send_sandbox_init"
ACT_SEND_SANDBOX_EXECUTE_COMMAND = "send_sandbox_execute_command"
ACT_SEND_SANDBOX_SUSPEND = "send_sandbox_suspend"
ACT_SEND_SANDBOX_RESUME = "send_sandbox_resume"
ACT_SEND_SANDBOX_SNAPSHOT = "send_sandbox_snapshot"
ACT_SEND_SANDBOX_DELETE_SNAPSHOT = "send_sandbox_delete_snapshot"

# ApplicationError type used when a provider does not support an operation;
# the workflow detects it and falls back to snapshot-based suspend.
ERR_UNSUPPORTED = "ErrUnsupported"

# Sentinel for idle_timeout_seconds meaning "never auto-suspend".
# Zero means "use the default" (config.SANDBOX_IDLE_TIMEOUT).
NO_IDLE_TIMEOUT = -1.0


# --- Compute provider value objects -------------------------------------------
@dataclass
class ProviderDetails:
    """Identifies a compute provider by registered type name plus its config."""

    type: str
    config: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderStatus:
    """Opaque handle to a provisioned compute instance."""

    instance_id: str


@dataclass
class ProviderSnapshot:
    """Opaque handle to a snapshot of a sandbox's filesystem state."""

    snapshot_id: str


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


class SandboxPostSnapshotState(IntEnum):
    """The sandbox's state after a provider Snapshot call returns."""

    RUNNING = 0  # still running; lifecycle unchanged
    SUSPENDED = 1  # provider paused it while snapshotting; resume restarts from snapshot
    DELETED = 2  # compute resource destroyed; sandbox workflow shuts down


class SandboxLifecycle(str, Enum):
    """Public lifecycle state, returned by the sandbox-state query."""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    SUSPENDED_WITH_SNAPSHOT = "suspended-with-snapshot"
    FAILED = "failed"
    DELETED = "deleted"


# --- SandboxWorkflow messages ---------------------------------------------------
@dataclass
class SandboxWorkflowInput:
    """Start argument for SandboxWorkflow: who the creator is (for logging)."""

    parent_workflow_id: str = ""
    parent_run_id: str = ""


@dataclass
class SandboxInitInput:
    compute_provider: ProviderDetails
    # 0 → default idle timeout; NO_IDLE_TIMEOUT (-1) → never auto-suspend.
    idle_timeout_seconds: float = 0.0
    # non-None → start from this snapshot instead of from scratch.
    snapshot: ProviderSnapshot | None = None


@dataclass
class SandboxExecuteCommandInput:
    command: str
    disable_auto_resume: bool = False


@dataclass
class SandboxState:
    """Result of the sandbox-state query."""

    lifecycle: SandboxLifecycle
    compute_provider: ProviderDetails | None = None
    status: ProviderStatus | None = None
    idle_timeout_seconds: float = 0.0


# --- Lifecycle activity messages -------------------------------------------------
@dataclass
class StartSandboxInput:
    provider: ProviderDetails
    task_queue_name: str


@dataclass
class StartSandboxOutput:
    status: ProviderStatus


@dataclass
class StopSandboxInput:
    provider: ProviderDetails
    status: ProviderStatus


@dataclass
class SuspendSandboxInput:
    provider: ProviderDetails
    status: ProviderStatus


@dataclass
class ResumeSandboxInput:
    provider: ProviderDetails
    status: ProviderStatus


@dataclass
class ExecuteCommandInput:
    provider: ProviderDetails
    status: ProviderStatus
    command: str


@dataclass
class SnapshotSandboxInput:
    provider: ProviderDetails
    status: ProviderStatus


@dataclass
class SnapshotSandboxOutput:
    sandbox_state: SandboxPostSnapshotState
    snapshot: ProviderSnapshot


@dataclass
class StartSandboxFromSnapshotInput:
    provider: ProviderDetails
    task_queue_name: str
    snapshot: ProviderSnapshot


@dataclass
class DeleteSnapshotInput:
    provider: ProviderDetails
    snapshot: ProviderSnapshot


# --- Send-update activity messages ------------------------------------------------
# UpdateID comes from workflow.uuid4() in the parent so activity retries are
# deduplicated by Temporal and each update is applied exactly once.
@dataclass
class SendSandboxInitInput:
    sandbox_id: str
    update_id: str
    compute_provider: ProviderDetails
    idle_timeout_seconds: float = 0.0
    snapshot: ProviderSnapshot | None = None


@dataclass
class SendSandboxExecuteCommandInput:
    sandbox_id: str
    update_id: str
    command: str
    disable_auto_resume: bool = False


@dataclass
class SendSandboxSuspendInput:
    sandbox_id: str
    update_id: str


@dataclass
class SendSandboxResumeInput:
    sandbox_id: str
    update_id: str


@dataclass
class SendSandboxSnapshotInput:
    sandbox_id: str
    update_id: str


@dataclass
class SendSandboxDeleteSnapshotInput:
    sandbox_id: str
    update_id: str
    snapshot: ProviderSnapshot
