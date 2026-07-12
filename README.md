# 🧵 AgentLoom

**Durable multi-agent workflows, woven together with [Temporal](https://temporal.io).**

A loom weaves independent threads into one fabric. AgentLoom does the same with
LLM agents: each agent is a thread, Temporal is the loom, and the workflow is the
fabric — durable, resumable, and observable. If a worker crashes mid-pipeline,
execution resumes exactly where it left off. No lost LLM calls, no duplicate spend.

LLM calls go through [OpenRouter](https://openrouter.ai) (an OpenAI-compatible
proxy in front of Claude and other model providers). Every call is also traced
end-to-end: [Langfuse](https://langfuse.com) captures
the prompts/outputs, [Prometheus](https://prometheus.io) + [Grafana](https://grafana.com)
capture the Temporal execution metrics, and the whole local stack — Temporal, the
worker, Prometheus, Grafana, and Langfuse — is orchestrated by [Flox](https://flox.dev)
as a single set of services.

## Architecture

```
                              ┌─────────────────────────────────────────┐
                              │              Flox environment             │
                              │  (flox services start/stop/status)       │
                              └─────────────────────────────────────────┘
                                                  │ manages
        ┌─────────────────────────────────────────┼─────────────────────────────────────────┐
        │                                          │                                          │
        ▼                                          ▼                                          ▼
┌───────────────────┐                    ┌───────────────────┐                    ┌───────────────────┐
│  Temporal server   │◀──gRPC :7233──────│  AgentLoom worker  │──HTTPS───▶ OpenRouter
│  (dev mode)        │   Web UI :8233     │  (worker.py)        │           (proxies to Claude)
│  metrics :9091      │                    │  SDK metrics :9464  │
└─────────┬──────────┘                    └─────────┬──────────┘
          │ scraped by                               │ scraped by, and traces sent by
          ▼                                          ▼
┌───────────────────┐                    ┌───────────────────────────┐
│    Prometheus       │◀── scrapes both ──│   Langfuse (docker compose) │
│    :9090             │                   │   web :3001, worker :3030,  │
└─────────┬──────────┘                    │   postgres/clickhouse/redis/ │
          │ datasource                     │   minio (internal ports)     │
          ▼                                └───────────────────────────┘
┌───────────────────┐
│      Grafana        │
│      :3000           │
└───────────────────┘

CLI: start_workflow.py ──executes workflow──▶ Temporal ──schedules activity──▶ worker
```

**Request flow:** `start_workflow.py` submits a `LoomWorkflow` run to Temporal.
Temporal schedules each agent step as an *activity* on the worker's task queue.
The worker picks up the activity, calls the LLM, records a Langfuse generation for
it, and returns the result to Temporal — which durably records it in workflow
history before scheduling the next step. Prometheus scrapes metrics from both
Temporal server and the worker; Grafana visualizes them.

See [docs/architecture.md](docs/architecture.md) for a deeper walkthrough of the
data flow and design decisions.

## Services

| Service | What it is | Port(s) | Docs |
|---|---|---|---|
| Temporal | Durable execution engine — the "loom" that schedules and persists every workflow/activity step | gRPC `7233`, Web UI `8233`, metrics `9091` | [docs/services/temporal.md](docs/services/temporal.md) |
| Worker | Python process hosting the workflow + activity code (`worker.py`) | SDK metrics `9464` | [docs/services/worker.md](docs/services/worker.md) |
| Activities | The generic LLM-calling activity all agents share (`activities/openai_responses.py`) | — | [docs/services/activities.md](docs/services/activities.md) |
| Workflows | The orchestration logic — `HelloWorld` and `LoomWorkflow` (`workflows/`) | — | [docs/services/workflows.md](docs/services/workflows.md) |
| Prometheus | Scrapes and stores metrics from Temporal server + the worker | `9090` | [docs/services/prometheus.md](docs/services/prometheus.md) |
| Grafana | Dashboards over the Prometheus metrics | `3000` | [docs/services/grafana.md](docs/services/grafana.md) |
| Langfuse | LLM observability — traces every prompt/response per workflow run | web `3001`, worker `3030` | [docs/services/langfuse.md](docs/services/langfuse.md) |
| Flox | Environment + service manager tying all of the above together | — | [docs/services/flox.md](docs/services/flox.md) |

## What's inside

| File | Purpose |
|---|---|
| `activities/openai_responses.py` | One generic LLM activity, reused by every agent, instrumented with Langfuse |
| `workflows/hello_world_workflow.py` | Single-agent starter (haiku bot) |
| `workflows/loom_workflow.py` | Multi-agent pipeline: parallel researchers → writer → critic |
| `worker.py` | Hosts workflows + activities on the `agentloom-task-queue`, exposes Prometheus metrics |
| `start_workflow.py` | Submits a run and prints the final brief |
| `observability/` | Prometheus config, Grafana dashboards/provisioning, Langfuse docker-compose stack |
| `.flox/env/manifest.toml` | Declares the dev environment and every service (`temporal`, `worker`, `prometheus`, `grafana`, `langfuse`) |
| `tests/` | Unit tests for the activity (mocked HTTP) and workflows (Temporal time-skipping test server) |

## Design decisions (Temporal best practices)

- **Retries belong to Temporal, not the SDK.** The activity makes a raw HTTP
  call with a short client-side timeout; Temporal's retry policy owns backoff
  and recovery.
- **Pydantic data converter** on both client and worker, so activity
  request/response types serialize cleanly through workflow history.
- **One generic activity, many agents.** Agents differ only by their
  instructions — the pipeline stays declarative inside the workflow.
- **Parallel fan-out with `asyncio.gather`** inside the workflow: Temporal
  schedules the researcher activities concurrently and records both results
  deterministically.
- **`workflow.unsafe.imports_passed_through()`** around the activities import,
  because `activities/openai_responses.py` imports `httpx`/`langfuse`, which
  the deterministic workflow sandbox rejects at workflow-code load time.

## The pipeline

```
                ┌──────────────────┐
        ┌──────▶│ Researcher (facts)│──┐
 topic ─┤       └──────────────────┘  ├──▶ Writer ──▶ Critic ──▶ final brief
        │       ┌──────────────────┐  │
        └──────▶│ Researcher       │──┘
                │ (misconceptions) │
                └──────────────────┘
```

## Quick start

Everything — Temporal, the worker, Prometheus, Grafana, and Langfuse — is
declared as a [Flox](https://flox.dev) service, so spinning up the full stack
is one command.

1. **Prerequisites:**
   - [Flox](https://flox.dev/docs/install-flox/) installed
   - [Docker](https://docs.docker.com/get-docker/) running (Langfuse's stack
     runs via `docker compose` under the hood)
   - An [OpenRouter](https://openrouter.ai/keys) API key (see `.env.example`)

2. **Set your API key** (in `.env`, or exported in your shell — see
   [docs/services/activities.md](docs/services/activities.md) for why `.env`
   alone isn't picked up automatically):

   ```sh
   export OPENROUTER_API_KEY=sk-or-v1-...
   ```

3. **Activate the environment and start every service:**

   ```sh
   flox activate --start-services
   ```

   This installs Python deps into a project-local venv, then starts:
   `temporal` → `worker` (waits for Temporal to be healthy) → `prometheus` →
   `grafana` → `langfuse` (via `docker compose up`).

4. **Check everything is up:**

   ```sh
   flox services status
   ```

5. **Kick off a workflow** (from another terminal, inside the Flox env — run
   `flox activate` there too):

   ```sh
   uv run python -m start_workflow "Vector databases"
   ```

6. **Watch it happen:**
   - Temporal Web UI — <http://localhost:8233> — step-by-step workflow/activity
     history. Kill the worker mid-run (`flox services stop worker`) and
     restart it (`flox services start worker`) to see durable execution pick
     up exactly where it stopped.
   - Grafana — <http://localhost:3000> — Temporal server + SDK dashboards
     (anonymous admin access, pre-provisioned).
   - Langfuse — <http://localhost:3001> — every LLM call as a generation,
     grouped into one trace per workflow run (local dev login seeded from
     `observability/langfuse/.env`).

For the full step-by-step spin-up → run → verify → teardown walkthrough
(including running without Flox), see
**[docs/e2e-testing.md](docs/e2e-testing.md)**.

## Running tests

```sh
uv run pytest
```

- `tests/test_activities.py` — the activity's HTTP call is mocked; no
  Temporal server or network access required.
- `tests/test_workflows.py` — runs real workflow code against Temporal's
  in-process time-skipping test server, with the `create` activity replaced
  by a scripted fake (so no LLM calls, but real Temporal scheduling/retry
  semantics).

## Extending the loom

- Add a new agent: one more `self._agent(...)` call in `loom_workflow.py`.
- Add a new provider: drop another generic activity next to
  `openai_responses.py` and register it in `worker.py`.
- Human in the loop: use Temporal signals to pause the loom for approval
  between the writer and critic steps.

## Documentation

- [docs/architecture.md](docs/architecture.md) — full architecture + data flow
- [docs/e2e-testing.md](docs/e2e-testing.md) — spin up every service and run an end-to-end test
- Per-service docs: [Temporal](docs/services/temporal.md) · [Worker](docs/services/worker.md) · [Activities](docs/services/activities.md) · [Workflows](docs/services/workflows.md) · [Prometheus](docs/services/prometheus.md) · [Grafana](docs/services/grafana.md) · [Langfuse](docs/services/langfuse.md) · [Flox](docs/services/flox.md)
