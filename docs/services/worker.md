# Worker

## What it is

The AgentLoom worker (`src/agentloom/worker.py`) is the Python process that actually
executes workflow and activity code. It connects to Temporal, long-polls
`agentloom-task-queue` for work, and runs whichever registered workflow
(`HelloWorld`, `LoomWorkflow`) or activity (`llm.run_llm`) Temporal
schedules.

```python
runtime = Runtime(
    telemetry=TelemetryConfig(
        metrics=PrometheusConfig(bind_address=config.WORKER_METRICS_ADDRESS)
    )
)
client = await Client.connect(
    config.TEMPORAL_ADDRESS,
    namespace=config.TEMPORAL_NAMESPACE,
    data_converter=pydantic_data_converter,
    runtime=runtime,
)
worker = Worker(
    client,
    task_queue=config.TASK_QUEUE,
    workflows=ALL_WORKFLOWS,
    activities=ALL_ACTIVITIES,
)
await worker.run()
```

New workflows/activities are picked up automatically: the worker registers
the `ALL_WORKFLOWS` list from `src/agentloom/workflows/__init__.py` and the
`ALL_ACTIVITIES` list from `src/agentloom/activities/__init__.py`.

Declared as the `worker` service in
[`.flox/env/manifest.toml`](../../.flox/env/manifest.toml), which waits for
Temporal to be healthy before launching:

```toml
[services.worker]
command = """
  cd "$FLOX_ENV_PROJECT"
  until temporal operator cluster health --address localhost:7233 >/dev/null 2>&1; do
    sleep 1
  done
  exec "$PYTHON_DIR/bin/python" -m agentloom.worker
"""
```

- Exposes Temporal SDK metrics (Prometheus format) on `127.0.0.1:9464`
  (overridable via `WORKER_METRICS_ADDRESS`).
- Uses the **pydantic data converter** on both worker and client, so
  `LLMRequest` (and any future Pydantic/dataclass activity payloads)
  serialize correctly into Temporal's protobuf-backed history.

## Why we need it

Temporal server only stores history and schedules work — it never executes
your code. Something has to actually run `LoomWorkflow.run` and
`llm.run_llm`. That's the worker. It's also the only place with
credentials to call OpenRouter (`OPENROUTER_API_KEY`), so it's the
security boundary between "durable orchestration" (Temporal, which never sees
your API key) and "the code that talks to external services."

## How to use it effectively

**Run it via Flox** (recommended — handles the wait-for-Temporal ordering):

```sh
flox services start worker
flox services logs worker --follow
```

**Run it standalone** (e.g. for local debugging with a debugger attached):

```sh
uv run python -m agentloom.worker
```

**Scale out:** start multiple worker processes pointed at the same task queue
(`agentloom-task-queue`) and Temporal load-balances activity/workflow tasks
across them automatically — no code changes needed. Useful for testing
worker-crash recovery (kill one, watch another pick up in-flight work) or for
increasing throughput.

**Change what address it connects to:** set `TEMPORAL_ADDRESS` (defaults to
`localhost:7233`) — e.g. to point a local worker at Temporal Cloud or a remote
dev cluster.

## Best practices

- **Register every workflow/activity the task queue needs, and nothing it
  doesn't.** New workflows go in `ALL_WORKFLOWS`
  (`src/agentloom/workflows/__init__.py`), new activities in `ALL_ACTIVITIES`
  (`src/agentloom/activities/__init__.py`) — if those lists drift from what
  workflow code actually calls, you get runtime "activity not registered"
  failures that only show up when that code path executes.
- **Keep worker startup idempotent and safe to restart.** The worker has no
  local state that matters — killing and restarting it is the normal recovery
  path, not an incident. That's the whole point of Temporal.
- **One task queue name, defined once.** `TASK_QUEUE` lives in
  `src/agentloom/config.py`; both the worker and the CLI import it from
  there, so renaming it is a one-line change.
- **Watch worker metrics, not just Temporal server metrics.** `:9464` exposes
  SDK-level detail (activity execution latency, poll success rate, sticky
  cache stats) that the server's own metrics don't show — this is what the
  "Temporal SDK" Grafana dashboard is built from. See
  [docs/services/grafana.md](grafana.md).

## Related links

- [Temporal Python SDK: Worker](https://python.temporal.io/temporalio.worker.Worker.html)
- [Temporal Python SDK: Pydantic converter](https://github.com/temporalio/sdk-python/tree/main/temporalio/contrib/pydantic)
- [Worker performance tuning](https://docs.temporal.io/develop/worker-performance)
