# Spinning up the full stack and running an end-to-end test

This walks through bringing up every service, running a real multi-agent
workflow through it, and verifying it in all three UIs (Temporal, Grafana,
Langfuse). For what each service is and why it exists, see
[docs/architecture.md](architecture.md) and the per-service docs linked from
the [README](../README.md#services).

## 0. Prerequisites

- [Flox](https://flox.dev/docs/install-flox/) installed
- [Docker](https://docs.docker.com/get-docker/) running (Langfuse's stack is
  five containers via `docker compose` — see
  [docs/services/langfuse.md](services/langfuse.md))
- An [OpenRouter](https://openrouter.ai/keys) API key
- [uv](https://docs.astral.sh/uv/) (bundled into the Flox env, but the
  `uv run` commands below assume it's on `PATH`)

## 1. Set your API key

Either export it before activating:

```sh
export OPENROUTER_API_KEY=sk-or-v1-...
```

or put it in a gitignored `.env` file at the repo root — the project's Flox
`on-activate` hook sources `.env` into the activated environment (see
[docs/services/flox.md](services/flox.md)), which is what makes it reach the
`worker` service. `worker.py` itself has no dotenv loading, so a bare `.env`
file with nothing sourcing it does nothing.

The activity (`activities/openai_responses.py`) reads
`OPENROUTER_API_KEY` directly from the environment and fails fast with a
clear error if it's unset — see
[docs/services/activities.md](services/activities.md).

> **Env var changes require a full restart, not `flox services restart`.**
> The Flox service manager captures its environment once, the first time
> `flox services start` (or `--start-services`) runs. Editing `.env` (or the
> manifest's `[vars]`) and then running `flox services restart worker` reuses
> the *old* captured environment — the new value won't show up. To apply an
> env change: `flox services stop` (stops everything) then
> `flox activate --start-services` again, so the hook re-sources `.env` into
> a fresh service-manager environment.

## 2. Activate the environment and start every service

```sh
flox activate --start-services
```

This runs Flox's `on-activate` hook (creates/updates a project-local venv,
`pip install -e .`s the repo), then starts, in dependency order handled by
each service's own command:

1. `temporal` — Temporal dev server (gRPC `7233`, Web UI `8233`, metrics `9091`)
2. `worker` — waits for `temporal operator cluster health` to succeed, then runs `worker.py`
3. `prometheus` — scrapes `temporal` + `worker` metrics on `9090`
4. `grafana` — dashboards on `3000`, auto-provisioned
5. `langfuse` — `docker compose up` for the full Langfuse stack (web `3001`, worker `3030`, plus Postgres/ClickHouse/Redis/MinIO)

## 3. Confirm everything is healthy

```sh
flox services status
```

Every service should show `Running`. `langfuse` typically takes the longest
(multiple containers with health checks) — give it 15–30s after the others
report running before assuming something's wrong. If a service isn't up,
tail its logs:

```sh
flox services logs <service-name> --follow
```

Spot-check each endpoint responds:

```sh
curl -sf http://localhost:8233 >/dev/null && echo "Temporal Web UI OK"
curl -sf http://localhost:9090/-/healthy && echo "Prometheus OK"
curl -sf http://localhost:3000/api/health && echo "Grafana OK"
curl -sf http://localhost:3001/api/public/health && echo "Langfuse OK"
```

## 4. Run the unit/integration test suite

Before an end-to-end run, confirm the code itself is correct in isolation —
this doesn't need any of the services above running:

```sh
uv run pytest
```

- `tests/test_activities.py` mocks the HTTP call — verifies the activity's
  request/response handling without a real API key or network access.
- `tests/test_workflows.py` runs the actual workflow code against Temporal's
  in-process time-skipping test server, with the `create` activity replaced
  by a scripted fake — verifies orchestration logic (fan-out, sequencing,
  retry-on-failure) without any LLM calls.

Both should pass before you spend real API budget on an end-to-end run.

## 5. Run a real end-to-end workflow

With the full stack up and `OPENROUTER_API_KEY` exported, submit a real run
(from a second terminal — run `flox activate` there too so `uv` is on `PATH`):

```sh
uv run python -m start_workflow "Vector databases"
```

This connects to Temporal, starts `LoomWorkflow`, and blocks until the full
pipeline (2 parallel researchers → writer → critic) completes, then prints
the final brief. A healthy run typically takes a few seconds to tens of
seconds, dominated by LLM latency.

## 6. Verify the run across all three UIs

**Temporal Web UI** — <http://localhost:8233>

- Find the workflow by ID (`loom-<uuid>`, printed nowhere by
  `start_workflow.py` today — search "Recent workflows" and match by start
  time, or add a `print(f"workflow id: {id}")` locally if you need it).
- Confirm: `WorkflowExecutionStarted` → 4 `ActivityTaskScheduled`/
  `ActivityTaskCompleted` pairs (2 researchers, writer, critic) → the writer's
  input includes both researchers' outputs → `WorkflowExecutionCompleted`.

**Grafana** — <http://localhost:3000> → Dashboards → Temporal folder

- `Temporal SDK` dashboard: you should see a spike in activity execution
  count/latency around the time of your run.
- `Temporal Server` dashboard: workflow/activity completion counters
  incrementing.

**Langfuse** — <http://localhost:3001>

- Find the trace with `session_id` = your workflow's ID.
- Confirm 4 generations under that session, each showing the real
  `instructions`/`input` sent and the model's actual output text — this is
  the fastest way to sanity-check prompt/output quality, not just "did it
  run."

## 7. Test durable recovery (optional but recommended)

This is the actual point of using Temporal — prove a mid-run crash doesn't
lose work:

```sh
flox services stop worker
uv run python -m start_workflow "Durable execution" &
sleep 2
flox services start worker
```

Watch the Temporal Web UI: the workflow's activities remain `Scheduled`
(not lost) while the worker is down, and complete once it reconnects — with
no duplicate LLM calls for any activity that had already finished before the
stop.

## 8. Tear down

```sh
flox services stop
```

Stops `temporal`, `worker`, `prometheus`, `grafana`, and runs `docker compose
down` for the Langfuse stack (containers stop; named volumes — and therefore
trace/workflow history — persist). To fully reset local state (fresh
Temporal history, fresh Langfuse data, fresh Grafana/Prometheus data), also
clear `.flox/cache/` and run `docker compose -f
observability/langfuse/docker-compose.yml down -v`.

## Running without Flox

If you'd rather not use Flox, each service can be run manually in its own
terminal, in this order:

```sh
# 1. Temporal dev server
temporal server start-dev --metrics-port 9091

# 2. Worker (after Temporal is healthy)
uv run python -m worker

# 3. Prometheus
prometheus --config.file=observability/prometheus.yml --web.listen-address=localhost:9090

# 4. Grafana (needs GF_PATHS_PROVISIONING pointed at observability/grafana/provisioning
#    and AGENTLOOM_DASHBOARDS_DIR pointed at observability/grafana/dashboards — see
#    the grafana service command in .flox/env/manifest.toml for the exact env vars)
grafana server

# 5. Langfuse
docker compose -f observability/langfuse/docker-compose.yml up
```

This is more error-prone (you own the startup ordering and env vars Flox
otherwise handles) — prefer `flox activate --start-services` unless you have
a specific reason not to use Flox.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `worker` service stuck / never becomes healthy | Temporal isn't reachable yet | `flox services logs temporal`; `temporal operator cluster health --address localhost:7233` |
| Activity fails with "Missing OPENROUTER_API_KEY" | Var not in the environment the `worker` service was started with — either it was never set, or it was added/changed *after* the service manager already captured its environment | Set it in `.env` or export it, then do a full `flox services stop` + `flox activate --start-services` (a plain `flox services restart worker` reuses the stale captured environment — see the callout in [step 1](#1-set-your-api-key)) |
| Activity fails with `401 Unauthorized` from `openrouter.ai` | The key value itself is invalid, revoked, or malformed — this is a credentials problem, not a code problem | Regenerate a key at [openrouter.ai/keys](https://openrouter.ai/keys); confirm it's the exact value in `.env` (no stray whitespace/quotes) |
| Activity fails with `404 Not Found` / model errors from `openrouter.ai` | The `MODEL` constant in `workflows/loom_workflow.py`/`hello_world_workflow.py` isn't a valid OpenRouter model slug | Check `GET https://openrouter.ai/api/v1/models` or [openrouter.ai/models](https://openrouter.ai/models) for the exact slug (e.g. `anthropic/claude-haiku-4.5`) |
| Grafana panels show "No data" | Prometheus scrape target down, or job name mismatch | [Prometheus targets page](http://localhost:9090/targets); see [docs/services/prometheus.md](services/prometheus.md) |
| `langfuse` service slow to report healthy | Multi-container stack (Postgres/ClickHouse/Redis/MinIO) with health-check dependencies | `flox services logs langfuse --follow`; `docker compose -f observability/langfuse/docker-compose.yml ps` |
| No trace appears in Langfuse for a run | `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` not set in the worker's environment | Confirm they're set under `[vars]` in `.flox/env/manifest.toml` and the `worker` service was started *after* that change |
| Port already in use on start | A previous non-Flox-managed process (e.g. a manually started `temporal server start-dev`) is holding the port | `lsof -i :<port>`; stop the stray process rather than changing the manifest's ports |
