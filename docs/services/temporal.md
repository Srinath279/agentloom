# Temporal

## What it is

[Temporal](https://temporal.io) is the durable execution engine — the "loom"
in AgentLoom. It's a server that persists every step of a workflow
(`WorkflowExecutionStarted`, `ActivityTaskScheduled`, `ActivityTaskCompleted`,
...) as an append-only event history, and a set of language SDKs (we use the
[Python SDK](https://github.com/temporalio/sdk-python)) that let application
code express multi-step, long-running processes as plain `async` functions.

Locally this runs as the **Temporal dev server** (`temporal server
start-dev`), a single-binary, in-memory-friendly Temporal cluster meant for
local development — not the production topology (that would be a multi-node
cluster with a real database, e.g. Cassandra/Postgres + Elasticsearch).

Declared as the `temporal` service in
[`.flox/env/manifest.toml`](../../.flox/env/manifest.toml):

```toml
[services.temporal]
command = """
  exec temporal server start-dev \
    --metrics-port 9091 \
    --db-filename "$FLOX_ENV_CACHE/temporal.db"
"""
```

- gRPC frontend (what the SDK talks to): `localhost:7233`
- Web UI: <http://localhost:8233>
- Internal server metrics (Prometheus format): `localhost:9091`
- State persisted to `$FLOX_ENV_CACHE/temporal.db` (SQLite) — survives
  restarts within the same Flox env cache.

## Why we need it

This is the entire reason AgentLoom is resumable: if the worker process dies
mid-pipeline (crash, deploy, OOM), Temporal has already durably recorded every
completed activity. When a worker reconnects, Temporal replays the recorded
history to reconstruct workflow state and resumes exactly at the next
undone step — no lost LLM calls, no re-running (and re-paying for) completed
agent steps. Without Temporal, a multi-agent pipeline is just an async
function that starts over from scratch on any crash.

## How to use it effectively

**Watch a run live:** open <http://localhost:8233>, find your workflow by ID
(e.g. `loom-<uuid>` from `src/agentloom/cli.py`), and inspect the event history —
every activity's input, output, retries, and timing.

**Prove durability to yourself:**

```sh
flox services stop worker
uv run python -m agentloom.cli "Durable execution" &
sleep 2
flox services start worker
```

Watch the Web UI: the workflow picks up and completes once the worker comes
back, without re-running activities that already finished.

**Inspect a specific workflow from the CLI:**

```sh
temporal workflow show --workflow-id loom-<uuid>
temporal workflow list
```

**Query the dev server's health** (used internally by the `worker` service to
know when to start):

```sh
temporal operator cluster health --address localhost:7233
```

## Best practices

- **The dev server is for local dev only.** It uses SQLite and has no
  clustering/HA — don't point production traffic at `start-dev`. For
  production, use [Temporal Cloud](https://temporal.io/cloud) or a
  self-hosted cluster.
- **Workflow code must be deterministic.** No direct network/file I/O,
  randomness, or wall-clock reads inside `@workflow.run` methods — Temporal
  replays workflow code from history, and replay must produce identical
  decisions. All real-world side effects belong in activities. See
  [docs/services/workflows.md](workflows.md) and
  [docs/services/activities.md](activities.md).
- **Give activities explicit timeouts.** Every `workflow.execute_activity`
  call here sets `start_to_close_timeout` — without one, a hung activity can
  block a workflow indefinitely.
- **One task queue per worker pool.** All workflows/activities here share
  `agentloom-task-queue` (defined in `src/agentloom/worker.py` and `src/agentloom/cli.py`) —
  keep client and worker queue names in sync, or workflows will never be
  picked up.
- **Use workflow IDs meaningfully.** `src/agentloom/cli.py` generates
  `loom-<uuid>`; consider deterministic IDs (e.g. derived from input) if you
  want Temporal's built-in dedup ("don't start a second workflow for the same
  logical request") rather than a fresh run every time.

## Related links

- [Temporal docs](https://docs.temporal.io/)
- [Temporal Python SDK](https://docs.temporal.io/dev-guide/python)
- [Temporal dev server guide](https://docs.temporal.io/cli#start-dev)
- [Determinism constraints](https://docs.temporal.io/workflows#deterministic-constraints)
- [Retry policies](https://docs.temporal.io/encyclopedia/retry-policies)
