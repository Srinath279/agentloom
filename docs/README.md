# AgentLoom documentation

## Start here

- [architecture.md](architecture.md) — components, request flow, and why the
  design looks the way it does
- [e2e-testing.md](e2e-testing.md) — spin up the full local stack (Flox),
  run a real workflow, verify it in every UI, test crash recovery

## Deployment

- [deployment/kubernetes.md](deployment/kubernetes.md) — build the worker
  image and deploy to a cluster with Kustomize (dev/prod overlays)

## Per-service reference

| Doc | Covers |
|---|---|
| [services/temporal.md](services/temporal.md) | Temporal server — the durable execution engine |
| [services/worker.md](services/worker.md) | The worker process (`agentloom.worker`) |
| [services/activities.md](services/activities.md) | The shared LLM activity (`agentloom.activities.llm`) |
| [services/workflows.md](services/workflows.md) | Workflow orchestration and the agent catalog |
| [services/sandbox.md](services/sandbox.md) | Ephemeral compute sandboxes (`agentloom.sandbox`) |
| [services/prometheus.md](services/prometheus.md) | Metrics scraping |
| [services/grafana.md](services/grafana.md) | Dashboards |
| [services/loki.md](services/loki.md) | Log storage (worker logs via Alloy) |
| [services/langfuse.md](services/langfuse.md) | LLM trace observability |
| [services/flox.md](services/flox.md) | The local environment + service manager |

## Roadmap

- [roadmap.md](roadmap.md) — planned features: MCP tools,
  richer multi-agent patterns, agent memory, LLM knowledge wiki, agent skills
