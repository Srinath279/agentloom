# 🧵 AgentLoom

**Durable multi-agent workflows, woven together with [Temporal](https://temporal.io).**

A loom weaves independent threads into one fabric. AgentLoom does the same with
LLM agents: each agent is a thread, Temporal is the loom, and the workflow is the
fabric — durable, resumable, and observable. If a worker crashes mid-pipeline,
execution resumes exactly where it left off. No lost LLM calls, no duplicate spend.

```
                ┌──────────────────┐
        ┌──────▶│ Researcher (facts)│──┐
 topic ─┤       └──────────────────┘  ├──▶ Writer ──▶ Critic ──▶ final brief
        │       ┌──────────────────┐  │
        └──────▶│ Researcher       │──┘
                │ (misconceptions) │
                └──────────────────┘
```

LLM calls go through any OpenAI-compatible endpoint —
[OpenRouter](https://openrouter.ai) by default, or a local server like Ollama.
Every call is traced ([Langfuse](https://langfuse.com)), every execution is
measured ([Prometheus](https://prometheus.io) + [Grafana](https://grafana.com)),
and the whole local stack is one command via [Flox](https://flox.dev).

## Repository layout

```
src/agentloom/          the application package
├── config.py           core env-driven settings, defined once
├── agents/             declarative agent templates (AgentSpec + catalog)
├── activities/         non-deterministic work (the shared LLM activity)
├── workflows/          deterministic orchestration (HelloWorld, LoomWorkflow,
│                       ChatWorkflow — durable interactive chat,
│                       SandboxDemoWorkflow)
├── sandbox/            ephemeral compute sandboxes for agent shell commands
│                       (local Docker or E2B; suspend/resume, snapshot/fork)
├── api/                FastAPI control plane for the chat UI
├── worker.py           hosts ALL workflows + activities  → agentloom-worker
├── cli.py              submits a loom run                → agentloom-run
└── tools/ memory/ skills/    reserved for roadmap features

frontend/               React chat UI (Vite, :5173)

deploy/
├── docker/Dockerfile   worker image (multi-stage, non-root)
└── k8s/                Kustomize base + dev/prod overlays

observability/          local Prometheus/Grafana/Loki/Alloy/Langfuse configs
docs/                   architecture, per-service reference, deployment, roadmap
tests/                  activity/workflow tests
```

**The reusable template:** an agent is just an `AgentSpec` (name +
instructions + optional model override) in
[src/agentloom/agents/catalog.py](src/agentloom/agents/catalog.py). Every
agent runs through the same LLM activity; workflows compose specs. Adding an
agent = one spec + one `self._run_agent(...)` call. New workflows/activities
register themselves by joining the `ALL_WORKFLOWS` / `ALL_ACTIVITIES` lists.

**Sandboxes:** any workflow can run shell commands in isolated, durable
compute via [agentloom.sandbox](src/agentloom/sandbox/__init__.py) — a
Python port of Temporal's
[sandbox-orchestration-harness](https://github.com/temporal-community/sandbox-orchestration-harness):
`sbx = await Sandbox.create(ProviderDetails(type="local-docker"))`, then
`await sbx.execute_command("...")`. See
[docs/services/sandbox.md](docs/services/sandbox.md).

## Quick start (local)

1. **Prerequisites:** [Flox](https://flox.dev/docs/install-flox/),
   [Docker](https://docs.docker.com/get-docker/) (for Langfuse), and an
   [OpenRouter API key](https://openrouter.ai/keys) — or a local
   [Ollama](https://ollama.com) server instead (see `.env.example`).

2. **Configure:** copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.

3. **Start everything** (Temporal, worker, Prometheus, Grafana, Loki, Alloy,
   Langfuse):

   ```sh
   flox activate --start-services
   flox services status   # confirm all Running
   ```

4. **Run a workflow** (second terminal, `flox activate` there too):

   ```sh
   uv run python -m agentloom.cli "Vector databases"
   ```

5. **Watch it:** Temporal UI <http://localhost:8233> · Grafana
   <http://localhost:3000> · Langfuse <http://localhost:3001>.

Full walkthrough (including crash-recovery demo and running without Flox):
[docs/e2e-testing.md](docs/e2e-testing.md).

## The chat UI

The React frontend is a chat interface backed by durable agents: each
conversation is a `ChatWorkflow` (messages are Temporal signals, the
transcript is workflow state), so a chat survives page reloads and worker
crashes, and every reply is traced in Langfuse under the chat's session.

```sh
flox activate --start-services   # also starts the api and frontend services
open http://localhost:5173       # ask anything — first message starts a session
```

## Deploying to Kubernetes

The worker is stateless and scales horizontally — dev and prod are Kustomize
overlays over one base:

```sh
docker build -f deploy/docker/Dockerfile -t <registry>/agentloom-worker:dev .
kubectl -n agentloom-dev create secret generic agentloom-secrets \
  --from-literal=OPENROUTER_API_KEY=sk-or-v1-...
kubectl apply -k deploy/k8s/overlays/dev     # or overlays/prod
```

See [docs/deployment/kubernetes.md](docs/deployment/kubernetes.md) for
Temporal server options, scaling signals, and production notes.

## Tests

```sh
uv run pytest
```

Activity tests mock the HTTP layer; workflow tests run real orchestration
code against Temporal's in-process time-skipping test server. No network or
API key needed.

## Design decisions (Temporal best practices)

- **Retries belong to Temporal, not the SDK** — the activity makes one raw
  HTTP call; Temporal's retry policy owns backoff and recovery.
- **Determinism boundary** — workflows are deterministic; all I/O lives in
  activities (hence `workflow.unsafe.imports_passed_through()` around the
  activity import).
- **One generic activity, many agents** — agents differ only by their spec;
  the pipeline stays declarative inside the workflow.
- **Config defined once** — task queue, addresses, model, and timeouts live
  in [src/agentloom/config.py](src/agentloom/config.py) and are driven by the
  same env vars locally (`.env` via Flox) and in-cluster (ConfigMap/Secret).
- **Tracing follows the workflow, not the process** — Langfuse sessions key
  off `workflow_id`, so retries on other workers land in the same trace.

## Documentation

Everything lives under [docs/](docs/README.md):
[architecture](docs/architecture.md) ·
[local e2e guide](docs/e2e-testing.md) ·
[Kubernetes deployment](docs/deployment/kubernetes.md) ·
[sandboxes](docs/services/sandbox.md) ·
[roadmap](docs/roadmap.md) (MCP tools, agent memory, skills) ·
per-service reference in [docs/services/](docs/README.md#per-service-reference)
