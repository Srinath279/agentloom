"""Compute provider abstraction for sandboxes.

A provider knows how to provision, control, and destroy one kind of
ephemeral compute (local Docker containers here; E2B, Modal, Daytona,
AgentCore, GKE Agent Sandbox in the upstream Go harness). Providers
self-register in a process-wide registry keyed by type name, so activities
can reconstruct one from the serialized ``ProviderDetails`` alone.

Adding a provider = subclass :class:`ComputeProvider`, call
:func:`register` at module import, and import the module below.
"""

from abc import ABC, abstractmethod
from typing import Callable

from agentloom.sandbox.types import (
    CommandResult,
    ProviderDetails,
    ProviderSnapshot,
    ProviderStatus,
    SandboxPostSnapshotState,
)


class UnsupportedOperationError(Exception):
    """Raised by a provider when it does not support an operation.

    The sandbox workflow detects this (as an ``ErrUnsupported`` application
    error) and, for suspend, falls back to snapshot+stop.
    """


class ComputeProvider(ABC):
    """Interface a compute backend must implement to host sandboxes.

    Lifecycle contract (mirrors the Go harness):
      - ``start`` returns a ProviderStatus whose instance_id is sufficient to
        identify the sandbox in every subsequent call.
      - ``task_queue_name`` is the Temporal task queue an in-sandbox worker
        should poll, for providers that run workers inside the sandbox;
        providers may ignore it.
      - Unsupported operations must raise :class:`UnsupportedOperationError`.
      - ``snapshot`` returns the post-snapshot state of the origin sandbox;
        see :class:`SandboxPostSnapshotState`.
      - A non-zero command exit code is a *result*, not an error: return it
        in ``CommandResult.exit_code``.
    """

    @abstractmethod
    async def start(self, task_queue_name: str) -> ProviderStatus: ...

    @abstractmethod
    async def stop(self, status: ProviderStatus) -> None: ...

    @abstractmethod
    async def suspend(self, status: ProviderStatus) -> None: ...

    @abstractmethod
    async def resume(self, status: ProviderStatus) -> None: ...

    @abstractmethod
    async def snapshot(
        self, status: ProviderStatus
    ) -> tuple[SandboxPostSnapshotState, ProviderSnapshot]: ...

    @abstractmethod
    async def start_from_snapshot(
        self, task_queue_name: str, snapshot: ProviderSnapshot
    ) -> ProviderStatus: ...

    @abstractmethod
    async def delete_snapshot(self, snapshot: ProviderSnapshot) -> None: ...

    @abstractmethod
    async def execute_command(self, status: ProviderStatus, cmd: str) -> CommandResult: ...


Constructor = Callable[[dict[str, str]], ComputeProvider]

_registry: dict[str, Constructor] = {}


def register(provider_type: str, constructor: Constructor) -> None:
    """Add a constructor for the given provider type.

    Conventionally called at module import time. Raises if the type is
    already registered (mirrors the database/sql driver convention upstream).
    """
    if provider_type in _registry:
        raise ValueError(f"compute: provider already registered for type {provider_type!r}")
    _registry[provider_type] = constructor


def is_registered(provider_type: str) -> bool:
    return provider_type in _registry


def lookup(details: ProviderDetails) -> ComputeProvider:
    """Construct a provider from serialized details. Raises KeyError if unknown."""
    try:
        constructor = _registry[details.type]
    except KeyError:
        raise KeyError(f"no compute provider registered for type {details.type!r}") from None
    return constructor(details.config)


# Built-in providers self-register on import (kept at the bottom to avoid a
# circular import — they import register() from this module).
from agentloom.sandbox.compute import local_docker as _local_docker  # noqa: E402,F401

# E2B is optional: it registers only when the `e2b` package is installed
# (uv sync --extra e2b) — mirrors the upstream harness's e2b provider.
try:
    from agentloom.sandbox.compute import e2b as _e2b  # noqa: E402,F401
except ImportError:
    pass

__all__ = [
    "ComputeProvider",
    "UnsupportedOperationError",
    "register",
    "is_registered",
    "lookup",
    "CommandResult",
    "ProviderDetails",
    "ProviderSnapshot",
    "ProviderStatus",
    "SandboxPostSnapshotState",
]
