"""Sandbox orchestration: run shell commands in ephemeral, isolated compute
from Temporal workflows.

Python port of https://github.com/temporal-community/sandbox-orchestration-harness
as a reusable AgentLoom module. Each sandbox is a long-lived child workflow
(``SandboxWorkflow``) that provisions a compute instance via a pluggable
provider and handles suspend/resume, snapshot/fork, idle auto-suspend, and
teardown. Workflows drive it through the :class:`Sandbox` handle::

    from agentloom.sandbox import ProviderDetails, Sandbox

    sbx = await Sandbox.create(ProviderDetails(type="local-docker"))
    result = await sbx.execute_command("uname -a")
    await sbx.stop()

Providers: ``local-docker`` works out of the box; ``e2b`` when the ``e2b``
package is installed and ``E2B_API_KEY`` is set. Add your own by subclassing
:class:`agentloom.sandbox.compute.ComputeProvider` and calling
``compute.register``.

Worker wiring (already done in ``agentloom.worker``)::

    Worker(client,
           workflows=[*ALL_WORKFLOWS, *SANDBOX_WORKFLOWS],
           activities=[*ALL_ACTIVITIES, *sandbox_activities(client)])
"""

from agentloom.sandbox.handle import CleanupBehavior, Sandbox
from agentloom.sandbox.types import (
    NO_IDLE_TIMEOUT,
    CommandResult,
    ProviderDetails,
    ProviderSnapshot,
    ProviderStatus,
    SandboxLifecycle,
    SandboxState,
)
from agentloom.sandbox.workflow import SandboxWorkflow

SANDBOX_WORKFLOWS = [SandboxWorkflow]


def sandbox_activities(client) -> list:
    """All sandbox activities for worker registration; see activities.py.

    Imported lazily: activities pull in temporalio.client (and through it
    urllib), which Temporal's deterministic workflow sandbox rejects when it
    imports this package to load SandboxWorkflow.
    """
    from agentloom.sandbox.activities import sandbox_activities as build

    return build(client)

__all__ = [
    "Sandbox",
    "CleanupBehavior",
    "SandboxWorkflow",
    "SANDBOX_WORKFLOWS",
    "sandbox_activities",
    "NO_IDLE_TIMEOUT",
    "CommandResult",
    "ProviderDetails",
    "ProviderSnapshot",
    "ProviderStatus",
    "SandboxLifecycle",
    "SandboxState",
]
