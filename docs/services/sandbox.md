# Sandboxes — `agentloom.sandbox`

Run shell commands in ephemeral, isolated compute environments from any
workflow. A Python port of Temporal's
[sandbox-orchestration-harness](https://github.com/temporal-community/sandbox-orchestration-harness)
(Go), reshaped as a reusable AgentLoom module. This is the roadmap's
"Sandboxing" feature: agent-generated code and risky tool calls get an
isolated runtime with full Temporal durability per command.

## Using it from a workflow

```python
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from agentloom.sandbox import ProviderDetails, Sandbox

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self) -> str:
        sbx = await Sandbox.create(ProviderDetails(type="local-docker"))
        try:
            result = await sbx.execute_command("echo hello")
            return result.stdout        # also .stderr, .exit_code
        finally:
            await sbx.stop()
```

State persists between commands — it is the same compute instance. A
non-zero exit code is a *result* (`result.exit_code`), not an exception.

Try it end-to-end with the bundled demo workflow (stack running):

```sh
temporal workflow execute \
    --type SandboxDemoWorkflow --task-queue agentloom-task-queue \
    --workflow-id sandbox-demo -i '["echo hello from the sandbox", "uname -a"]'
```

## How it works

`Sandbox.create` starts a **child workflow** (`SandboxWorkflow`, workflow ID
= sandbox ID) that owns the compute instance's lifecycle. Every operation on
the handle runs one activity that forwards a **workflow update** to the
sandbox workflow — request/response semantics without breaking determinism.
Update IDs come from `workflow.uuid4()`, so activity retries are deduplicated
by Temporal and each update is applied exactly once.

```
Parent workflow                     SandboxWorkflow (child, ID = sandbox ID)
  Sandbox.create() ───────────────▶ sandbox-init update → start_sandbox activity
  sbx.execute_command() ──────────▶ sandbox-execute-command update → execute_command
  │                                   └─ idle timer starts after each command;
  │                                      auto-suspends when it expires
  sbx.suspend() / resume() ───────▶ sandbox-suspend / sandbox-resume updates
  sbx.snapshot() ─────────────────▶ sandbox-snapshot update
  sbx.stop() ─────────────────────▶ sandbox-stop signal → stop_sandbox, exit
```

Lifecycle behaviours (all ported from the Go harness):

- **Idle auto-suspend** — after each command an idle timer starts
  (`SANDBOX_IDLE_TIMEOUT_SECONDS`, default 5 min; override per sandbox with
  `Sandbox.create(idle_timeout_seconds=...)`, or disable with
  `NO_IDLE_TIMEOUT`).
- **Transparent resume** — running a command against a suspended sandbox
  resumes it first. Pass `disable_auto_resume=True` to get a `Suspended`
  error instead.
- **Suspend fallback** — providers without native suspend are suspended via
  snapshot+stop; the next resume restarts from that snapshot and deletes it.
- **Cleanup** — by default the sandbox is cancelled when its creator
  workflow closes (`CleanupBehavior.WITH_WORKFLOW`); pass
  `cleanup=CleanupBehavior.DISABLED` to let it outlive the creator (you must
  then `stop()` it explicitly).

### Snapshot and fork

```python
snap = await origin.snapshot()          # origin keeps running
fork_a = await Sandbox.create(provider, snapshot=snap)
fork_b = await Sandbox.create(provider, snapshot=snap)
```

Each fork is fully independent — writes in one are invisible to the others
and to the origin. Snapshots you take are yours to delete
(`sbx.delete_snapshot(snap)`); the module never auto-deletes them.

### Sharing a sandbox across workflows

```python
ref = sbx.ref()                         # opaque string, safe to pass around
# ... in a child or sibling workflow:
sbx = Sandbox.attach(ref)
await sbx.execute_command("ls")
```

Attached handles route commands to the same sandbox but do not own its
lifecycle: only the creator can `stop()` and wait for completion.

## Compute providers

A provider is looked up by name from `ProviderDetails(type=..., config=...)`:

| Type | Backing | Needs |
|---|---|---|
| `local-docker` | containers on the local Docker daemon | Docker (already a stack prerequisite) |
| `e2b` | [E2B](https://e2b.dev) cloud sandboxes | `uv sync --extra e2b`, `E2B_API_KEY` env var |

`local-docker` config keys: `image` (default `SANDBOX_DOCKER_IMAGE`,
`python:3.12-slim`) and `shell` (default `/bin/sh`). Suspend/resume map to
`docker pause`/`unpause`; snapshots are `docker commit` images. Containers
are labelled `agentloom.sandbox=true` — find strays with
`docker ps --filter label=agentloom.sandbox`.

`e2b` config keys: `template-id` (required) and `timeout` (sandbox lifetime
in seconds, default 3600). Resume is a no-op because E2B auto-resumes a
paused sandbox on the next command.

**Adding a provider** = one module: subclass
`agentloom.sandbox.compute.ComputeProvider` (eight async methods: start,
stop, suspend, resume, snapshot, start_from_snapshot, delete_snapshot,
execute_command), call `compute.register("my-type", MyProvider)` at module
import, and import the module from `agentloom/sandbox/compute/__init__.py`.
Raise `UnsupportedOperationError` for operations the backend can't do — the
workflow falls back automatically where possible (e.g. suspend via
snapshot). The upstream Go harness has reference implementations for Modal,
Daytona, AWS AgentCore, and GKE Agent Sandbox.

## Worker registration

Already wired in `agentloom.worker`; for a custom worker:

```python
from agentloom.sandbox import SANDBOX_WORKFLOWS, sandbox_activities

worker = Worker(
    client,
    task_queue=...,
    workflows=[*my_workflows, *SANDBOX_WORKFLOWS],
    activities=[*my_activities, *sandbox_activities(client)],
)
```

`sandbox_activities` needs the Temporal client because the send-update
activities call `client.execute_update` on the sandbox workflow.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SANDBOX_DOCKER_IMAGE` | `python:3.12-slim` | image for `local-docker` sandboxes |
| `SANDBOX_OPERATION_TIMEOUT_SECONDS` | `600` | per-operation activity timeout |
| `SANDBOX_COMMAND_TIMEOUT_SECONDS` | `1200` | end-to-end command timeout (incl. transparent resume) |
| `SANDBOX_IDLE_TIMEOUT_SECONDS` | `300` | default idle auto-suspend timeout |

## Module layout

```
src/agentloom/sandbox/
├── __init__.py        public API (Sandbox, SANDBOX_WORKFLOWS, sandbox_activities)
├── types.py           dataclasses + wire names (stdlib-only, workflow-safe)
├── handle.py          Sandbox handle used inside workflows
├── workflow.py        SandboxWorkflow (update/signal/query handlers)
├── activities.py      provider lifecycle + send-update activities
└── compute/           provider abstraction, registry, local_docker, e2b
```

One porting gotcha worth knowing: workflow files must import
`agentloom.sandbox` inside `workflow.unsafe.imports_passed_through()`, and
module-internal imports use the dotted `import agentloom.sandbox.types as t`
form — a `from agentloom.sandbox import compute` inside a passthrough block
is resolved by CPython's fromlist machinery, silently bypassing Temporal's
sandbox importer and producing a second copy of the provider registry.

Tests: `tests/test_sandbox.py` drives the real workflows and update
machinery against Temporal's test server with a scripted in-memory provider.
