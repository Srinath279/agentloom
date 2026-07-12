# Worker

## What it is

The AgentLoom worker (`worker.py`) is the Python process that actually
executes workflow and activity code. It connects to Temporal, long-polls
`agentloom-task-queue` for work, and runs whichever registered workflow
(`HelloWorld`, `LoomWorkflow`) or activity (`openai_responses.create`) Temporal
schedules.

```python
runtime = Runtime(
    telemetry=TelemetryConfig(
        metrics=PrometheusConfig(bind_address="127.0.0.1:9464")
    )
)
client = await Client.connect(
    os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
    data_converter=pydantic_data_converter,
    runtime=runtime,
)
worker = Worker(
    client,
    task_queue="agentloom-task-queue",
    workflows=[HelloWorld, LoomWorkflow],
    activities=[openai_responses.create],
)
await worker.run()
```

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
  exec "$PYTHON_DIR/bin/python" worker.py
"""
```

- Exposes Temporal SDK metrics (Prometheus format) on `127.0.0.1:9464`
  (overridable via `WORKER_METRICS_ADDRESS`).
- Uses the **pydantic data converter** on both worker and client, so
  `LLMResponsesRequest` (and any future Pydantic/dataclass activity payloads)
  serialize correctly into Temporal's protobuf-backed history.

## Why we need it

Temporal server only stores history and schedules work — it never executes
your code. Something has to actually run `LoomWorkflow.run` and
`openai_responses.create`. That's the worker. It's also the only place with
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
uv run python -m worker
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
  doesn't.** If `worker.py`'s `workflows=[...]`/`activities=[...]` lists drift
  from what workflow code actually calls, you get runtime "activity not
  registered" failures that only show up when that code path executes.
- **Keep worker startup idempotent and safe to restart.** The worker has no
  local state that matters — killing and restarting it is the normal recovery
  path, not an incident. That's the whole point of Temporal.
- **One task queue name, defined once.** `TASK_QUEUE = "agentloom-task-queue"`
  is duplicated in `worker.py` and `start_workflow.py` — if you rename it,
  update both (and anywhere else a client connects).
- **Watch worker metrics, not just Temporal server metrics.** `:9464` exposes
  SDK-level detail (activity execution latency, poll success rate, sticky
  cache stats) that the server's own metrics don't show — this is what the
  "Temporal SDK" Grafana dashboard is built from. See
  [docs/services/grafana.md](grafana.md).

## Related links

- [Temporal Python SDK: Worker](https://python.temporal.io/temporalio.worker.Worker.html)
- [Temporal Python SDK: Pydantic converter](https://github.com/temporalio/sdk-python/tree/main/temporalio/contrib/pydantic)
- [Worker performance tuning](https://docs.temporal.io/develop/worker-performance)
