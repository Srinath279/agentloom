"""E2B compute provider (https://e2b.dev), ported from the Go harness.

Optional: this module only registers itself when the ``e2b`` package is
installed (``uv add e2b`` or ``uv sync --extra e2b``). Requires the
``E2B_API_KEY`` environment variable on the worker.

Config keys:
  template-id  E2B sandbox template to launch (required, e.g. "base")
  timeout      sandbox lifetime in seconds (default 3600)

Behaviour mirrors the upstream Go provider:
  - suspend uses E2B's pause API; resume is a no-op because E2B
    auto-resumes a paused sandbox on the next command;
  - snapshot uses E2B's snapshots API and leaves the origin running;
  - a snapshot is deleted through the templates API.
The lifecycle calls the SDK covers (create/connect/kill/run) go through
the official ``e2b`` SDK; pause/snapshot/delete-snapshot use the same REST
endpoints as the Go provider via httpx.
"""

import os

import httpx
from e2b import AsyncSandbox

try:  # non-zero command exits surface as this exception in the e2b SDK
    from e2b import CommandExitException
except ImportError:  # pragma: no cover - older SDK layout
    from e2b.sandbox.commands.command_handle import CommandExitException

from agentloom.sandbox import compute
from agentloom.sandbox.types import (
    CommandResult,
    ProviderSnapshot,
    ProviderStatus,
    SandboxPostSnapshotState,
)

PROVIDER_TYPE_E2B = "e2b"

_API_BASE = "https://api.e2b.app"


class E2BProvider(compute.ComputeProvider):
    def __init__(self, provider_config: dict[str, str]):
        self._api_key = os.environ.get("E2B_API_KEY", "")
        if not self._api_key:
            raise ValueError("e2b: E2B_API_KEY env var required")
        self._template_id = provider_config.get("template-id", "")
        if not self._template_id:
            raise ValueError("e2b: template-id required")
        self._timeout = int(provider_config.get("timeout", "3600"))

    async def _api(self, method: str, path: str, ok: tuple[int, ...]) -> dict:
        async with httpx.AsyncClient(base_url=_API_BASE) as client:
            resp = await client.request(
                method, path, headers={"X-API-Key": self._api_key}, timeout=60.0
            )
        if resp.status_code not in ok:
            raise RuntimeError(f"e2b: {method} {path} returned {resp.status_code} - {resp.text}")
        return resp.json() if resp.content else {}

    async def _create(self, template: str, task_queue_name: str) -> ProviderStatus:
        sbx = await AsyncSandbox.create(
            template=template,
            timeout=self._timeout,
            envs={"TEMPORAL_TASK_QUEUE": task_queue_name},
            api_key=self._api_key,
        )
        return ProviderStatus(instance_id=sbx.sandbox_id)

    async def start(self, task_queue_name: str) -> ProviderStatus:
        return await self._create(self._template_id, task_queue_name)

    async def stop(self, status: ProviderStatus) -> None:
        # kill returns False when the sandbox is already gone; that's fine.
        await AsyncSandbox.kill(status.instance_id, api_key=self._api_key)

    async def suspend(self, status: ProviderStatus) -> None:
        await self._api("POST", f"/sandboxes/{status.instance_id}/pause", ok=(204,))

    async def resume(self, status: ProviderStatus) -> None:
        # E2B auto-resumes a paused sandbox when the next command connects,
        # so an explicit resume is a no-op (same as the Go provider).
        return None

    async def snapshot(
        self, status: ProviderStatus
    ) -> tuple[SandboxPostSnapshotState, ProviderSnapshot]:
        data = await self._api(
            "POST", f"/sandboxes/{status.instance_id}/snapshots", ok=(201,)
        )
        return SandboxPostSnapshotState.RUNNING, ProviderSnapshot(
            snapshot_id=data["snapshot_id"]
        )

    async def start_from_snapshot(
        self, task_queue_name: str, snapshot: ProviderSnapshot
    ) -> ProviderStatus:
        return await self._create(snapshot.snapshot_id, task_queue_name)

    async def delete_snapshot(self, snapshot: ProviderSnapshot) -> None:
        await self._api("DELETE", f"/templates/{snapshot.snapshot_id}", ok=(204, 404))

    async def execute_command(self, status: ProviderStatus, cmd: str) -> CommandResult:
        sbx = await AsyncSandbox.connect(status.instance_id, api_key=self._api_key)
        try:
            result = await sbx.commands.run(cmd)
        except CommandExitException as err:
            return CommandResult(
                stdout=err.stdout, stderr=err.stderr, exit_code=err.exit_code
            )
        return CommandResult(
            stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code
        )


# Guarded because Temporal's workflow sandbox may re-import this module
# against the already-populated passed-through registry.
if not compute.is_registered(PROVIDER_TYPE_E2B):
    compute.register(PROVIDER_TYPE_E2B, E2BProvider)
