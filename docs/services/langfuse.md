# Langfuse

## What it is

[Langfuse](https://langfuse.com) is the LLM observability layer — it captures
every prompt, response, latency, and error for every agent call, and groups
them into traces you can browse. Where Prometheus/Grafana show you *system*
health (latency, retries, throughput), Langfuse shows you *content*: what did
the researcher agent actually say, what prompt produced it, did the critic's
edit make sense.

It runs as a small self-hosted stack via
[`observability/langfuse/docker-compose.yml`](../../observability/langfuse/docker-compose.yml):

| Container | Role | Host port |
|---|---|---|
| `langfuse-web` | UI + API | `3001` (remapped — Grafana owns `3000`) |
| `langfuse-worker` | async ingestion processing | `3030` |
| `postgres` | primary metadata store | `5432` |
| `clickhouse` | trace/event analytics store | `8123`, `9000` |
| `redis` | queue for ingestion jobs | `6379` |
| `minio` | S3-compatible blob storage (event/media payloads) | `9190`, `9191` (remapped — Prometheus owns `9090`) |

Declared as the `langfuse` service in
[`.flox/env/manifest.toml`](../../.flox/env/manifest.toml), which just shells
out to `docker compose up` for that file — so it requires **Docker
running**, unlike every other service here which is a native Flox-installed
binary.

Local-dev credentials and a seeded org/project/user are defined in
[`observability/langfuse/.env`](../../observability/langfuse/.env) — throwaway
localhost-only secrets, safe to keep in git (see the comment at the top of
that file). The seeded project's public/secret keys
(`pk-lf-agentloom-local` / `sk-lf-agentloom-local`) and host
(`http://localhost:3001`) are wired into the Flox environment's `[vars]` in
`manifest.toml`, so the worker picks them up automatically — no manual login
or API-key copy-paste needed for local dev.

## Why we need it

`activities/openai_responses.py` wraps every LLM call in a Langfuse
`generation`, tagged with the owning Temporal workflow's ID as `session_id`
(see [docs/services/activities.md](activities.md)). That's what lets you open
Langfuse and see **one trace per `LoomWorkflow` run**, containing all four
agent calls (two researchers, writer, critic) in order — including the actual
prompt text, response text, and timing of each — which Temporal's own Web UI
doesn't show (Temporal records that an activity ran and what it returned, not
a prompt-engineering-friendly view of LLM I/O).

## How to use it effectively

**Open it:** <http://localhost:3001> — log in with the seeded user
(`LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` in
`observability/langfuse/.env`), or use the pre-created project's API keys
directly if calling Langfuse's API yourself.

**Find one workflow's full trace:** search/filter by session ID = the
Temporal workflow ID (e.g. `loom-<uuid>`) — every agent step of that run
groups into one trace.

**Iterate on prompts:** since `instructions`/`input` are captured as the
generation's `input`, you can compare researcher vs. writer vs. critic prompts
side-by-side across runs to see how instruction changes affect output quality
— without re-reading Temporal history JSON.

**Debug a failed agent call:** failed activities mark their Langfuse
generation `level="ERROR"` with the exception message
(`activities/openai_responses.py`) — filter by error level in Langfuse to find
failing calls faster than scanning Temporal history.

## Best practices

- **Never reuse the seeded local keys anywhere real.** `pk-lf-agentloom-local`
  / `sk-lf-agentloom-local` and every `# CHANGEME`-marked value in
  `docker-compose.yml` are dev-only placeholders — regenerate all of them
  (the `.env` comments say how, e.g. `openssl rand -hex 32` for
  `ENCRYPTION_KEY`) before running this stack anywhere beyond localhost.
- **This is a heavier service than the rest of the stack.** It's five
  containers (Postgres, ClickHouse, Redis, MinIO, plus the two Langfuse
  processes) — expect it to take noticeably longer to become healthy than
  `temporal`/`prometheus`/`grafana`. Don't assume it's broken if
  `flox services status` shows it starting for 15–30s.
- **Group by session, not by trace, for multi-agent pipelines.** The
  `session_id = workflow_id` convention here is what makes a 4-activity
  pipeline readable as one unit — if you add new workflows, keep deriving
  `session_id` from `activity.info().workflow_id` rather than inventing a new
  scheme per workflow.
- **Port remapping is deliberate — check it before assuming a service is
  down.** Langfuse's web UI is `3001` (not the Langfuse-default `3000`,
  since Grafana owns that here) and MinIO is `9190`/`9191` (not `9000`/`9001`,
  clear of Prometheus's `9090`). Cross-reference
  `observability/langfuse/docker-compose.yml` before debugging a "port in
  use" or "can't connect" issue.
- **Data lives in named Docker volumes**
  (`langfuse_postgres_data`, `langfuse_clickhouse_data`, etc.) — `docker
  compose down -v` on this file wipes trace history; plain `docker compose
  down` (or stopping via `flox services stop langfuse`) does not.

## Related links

- [Langfuse docs](https://langfuse.com/docs)
- [Langfuse self-hosting guide](https://langfuse.com/self-hosting)
- [Langfuse Python SDK v3](https://langfuse.com/docs/sdk/python/sdk-v3)
- [Langfuse + sessions/traces model](https://langfuse.com/docs/tracing)
- Local overrides: [`observability/langfuse/.env`](../../observability/langfuse/.env)
