"""Local Docker compute provider.

Implements the full ComputeProvider contract against the local Docker
daemon, so sandboxes work out of the box on any machine running this
stack (Docker is already a prerequisite for Langfuse):

  start               → docker run -d <image> sleep infinity
  execute_command     → docker exec <id> <shell> -c <cmd>
  suspend / resume    → docker pause / docker unpause
  snapshot            → docker commit (origin keeps running)
  start_from_snapshot → docker run -d <committed image>
  delete_snapshot     → docker rmi
  stop                → docker rm -f

Config keys (all optional):
  image  container image to run (default: config.SANDBOX_DOCKER_IMAGE)
  shell  shell used for execute_command (default: /bin/sh)
"""

import asyncio
import logging

from agentloom import config
from agentloom.sandbox import compute
from agentloom.sandbox.types import (
    CommandResult,
    ProviderSnapshot,
    ProviderStatus,
    SandboxPostSnapshotState,
)

log = logging.getLogger("agentloom.sandbox.local_docker")

PROVIDER_TYPE_LOCAL_DOCKER = "local-docker"

# Label applied to every sandbox container so strays are easy to find:
#   docker ps --filter label=agentloom.sandbox
_SANDBOX_LABEL = "agentloom.sandbox=true"


class LocalDockerProvider(compute.ComputeProvider):
    def __init__(self, provider_config: dict[str, str]):
        self._image = provider_config.get("image", config.SANDBOX_DOCKER_IMAGE)
        self._shell = provider_config.get("shell", "/bin/sh")

    async def _docker(self, *args: str) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode(), stderr.decode(), proc.returncode or 0

    async def _docker_checked(self, *args: str) -> str:
        """Run a docker command where a non-zero exit is a provider failure."""
        stdout, stderr, code = await self._docker(*args)
        if code != 0:
            raise RuntimeError(f"docker {args[0]} failed (exit {code}): {stderr.strip()}")
        return stdout.strip()

    async def _run_container(self, image: str) -> ProviderStatus:
        container_id = await self._docker_checked(
            "run", "-d", "--label", _SANDBOX_LABEL, image, "sleep", "infinity"
        )
        log.info("started sandbox container %s from %s", container_id[:12], image)
        return ProviderStatus(instance_id=container_id)

    async def start(self, task_queue_name: str) -> ProviderStatus:
        # task_queue_name is for providers that run a Temporal worker inside
        # the sandbox; a plain container has no worker, so it is unused here.
        return await self._run_container(self._image)

    async def stop(self, status: ProviderStatus) -> None:
        await self._docker_checked("rm", "-f", status.instance_id)

    async def suspend(self, status: ProviderStatus) -> None:
        await self._docker_checked("pause", status.instance_id)

    async def resume(self, status: ProviderStatus) -> None:
        await self._docker_checked("unpause", status.instance_id)

    async def snapshot(
        self, status: ProviderStatus
    ) -> tuple[SandboxPostSnapshotState, ProviderSnapshot]:
        # docker commit briefly pauses the container and leaves it running,
        # so the origin sandbox's lifecycle is unchanged.
        image_id = await self._docker_checked("commit", status.instance_id)
        return SandboxPostSnapshotState.RUNNING, ProviderSnapshot(snapshot_id=image_id)

    async def start_from_snapshot(
        self, task_queue_name: str, snapshot: ProviderSnapshot
    ) -> ProviderStatus:
        return await self._run_container(snapshot.snapshot_id)

    async def delete_snapshot(self, snapshot: ProviderSnapshot) -> None:
        await self._docker_checked("rmi", "-f", snapshot.snapshot_id)

    async def execute_command(self, status: ProviderStatus, cmd: str) -> CommandResult:
        stdout, stderr, code = await self._docker(
            "exec", status.instance_id, self._shell, "-c", cmd
        )
        # docker exec propagates the command's exit code; codes 125-127 are
        # docker/shell-level failures (daemon error, container paused or
        # gone, shell missing) that should fail — and retry — the activity.
        if code >= 125:
            raise RuntimeError(f"docker exec failed (exit {code}): {stderr.strip()}")
        return CommandResult(stdout=stdout, stderr=stderr, exit_code=code)


# Guarded because Temporal's workflow sandbox may re-import this module
# against the already-populated passed-through registry.
if not compute.is_registered(PROVIDER_TYPE_LOCAL_DOCKER):
    compute.register(PROVIDER_TYPE_LOCAL_DOCKER, LocalDockerProvider)
