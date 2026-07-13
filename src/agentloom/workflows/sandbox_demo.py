"""SandboxDemoWorkflow: run shell commands in an ephemeral sandbox.

The smallest end-to-end demonstration of the sandbox module: create a
local-docker sandbox, run each command in order (state persists between
commands — it's the same container), and return the results.

Run it against the local stack with:

    temporal workflow execute \\
        --type SandboxDemoWorkflow --task-queue agentloom-task-queue \\
        --workflow-id sandbox-demo -i '["echo hello from the sandbox", "uname -a"]'
"""

from temporalio import workflow

from agentloom import config

# agentloom.sandbox pulls in the compute providers (httpx etc.), which the
# deterministic workflow sandbox must not re-import — pass it through.
with workflow.unsafe.imports_passed_through():
    from agentloom.sandbox import CommandResult, ProviderDetails, Sandbox
    from agentloom.sandbox.compute.local_docker import PROVIDER_TYPE_LOCAL_DOCKER


@workflow.defn
class SandboxDemoWorkflow:
    @workflow.run
    async def run(
        self, commands: list[str], provider: ProviderDetails | None = None
    ) -> list[CommandResult]:
        # Default to local Docker; pass a second input to target another
        # provider, e.g. -i '{"type": "e2b", "config": {"template-id": "base"}}'
        if provider is None:
            provider = ProviderDetails(
                type=PROVIDER_TYPE_LOCAL_DOCKER,
                config={"image": config.SANDBOX_DOCKER_IMAGE},
            )
        sbx = await Sandbox.create(provider)
        try:
            return [await sbx.execute_command(cmd) for cmd in commands]
        finally:
            await sbx.stop()
