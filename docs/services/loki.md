# Loki + Promtail

## What it is

[Loki](https://grafana.com/oss/loki/) is Grafana's log-aggregation
datastore — like Prometheus, but for logs instead of metrics.
[Promtail](https://grafana.com/docs/loki/latest/send-data/promtail/) is the
agent that tails a log file and ships each line into Loki. Together they let
you search and stream the `worker` service's logs from inside Grafana instead
of `flox services logs worker -f`.

Both binaries ship in the single `grafana-loki` package
(`.flox/env/manifest.toml` → `[install]`), declared as two services:

- **`loki`** — filesystem-backed, single-binary mode, configured by
  [`observability/loki.yml`](../../observability/loki.yml). Listens on
  `:3100`, stores chunks/index under `$FLOX_ENV_CACHE/loki`.
- **`promtail`** — configured by
  [`observability/promtail.yml`](../../observability/promtail.yml). Tails
  `$FLOX_ENV_CACHE/worker.log` and pushes every line to Loki's
  `/loki/api/v1/push` endpoint, labeled `job=agentloom-worker`.

The worker only writes to that log file because `worker.py`'s
`_configure_logging()` adds a `logging.FileHandler` when `WORKER_LOG_FILE` is
set — which the `[services.worker]` command does, pointing it at
`$FLOX_ENV_CACHE/worker.log`. Both configs use `-config.expand-env=true` so
`${FLOX_ENV_CACHE}` resolves at startup, matching how `prometheus` and
`grafana` already use `$FLOX_ENV_CACHE` for their own data directories.

Grafana auto-provisions a `Loki` datasource from
[`observability/grafana/provisioning/datasources/loki.yml`](../../observability/grafana/provisioning/datasources/loki.yml),
the same mechanism that provisions the `Prometheus` datasource.

## Why we need it

`flox services logs worker` only shows what process-compose captured in its
own rotating log file, which changes path every time you `flox activate` and
interleaves every service's stdout together. Piping the worker's own log file
into Loki gives durable, queryable, worker-only logs that live alongside the
Temporal metrics dashboards already in Grafana — one pane for "is this
running" (Prometheus/Grafana) and "what actually happened" (Loki/Grafana),
instead of switching to a terminal for the second question.

## How to use it effectively

**View live logs:** Grafana (<http://localhost:3000>) → Explore → select the
`Loki` datasource → query `{job="agentloom-worker"}`. Add `|= "ERROR"` (LogQL
line filter) to narrow to failures, e.g. while chasing the stuck-activity
retries described in [docs/services/activities.md](activities.md).

**Correlate with a workflow run:** every activity failure logged by the
Temporal SDK includes the `workflow_id` in its message — search
`{job="agentloom-worker"} |= "loom-<id>"` to pull just that run's lines out of
the interleaved stream.

**Add more log sources:** point another `__path__` glob at a second
`scrape_configs` entry in `observability/promtail.yml`, or add a label to
distinguish sources — don't spin up a second Promtail service for it.

## Best practices

- **The log file is derived state, not source of truth.** `worker.log` lives
  under `$FLOX_ENV_CACHE`, same as `temporal.db` and `prometheus-data` — it's
  gitignored and safe to delete; Loki/Promtail will just start fresh.
- **`-config.expand-env=true` is required on both binaries.** Without it,
  `${FLOX_ENV_CACHE}` in `loki.yml`/`promtail.yml` is treated as a literal
  string, and both services will write into a directory literally named
  `${FLOX_ENV_CACHE}`.
- **Keep the datasource UID (`loki`) stable**, same reasoning as the
  `prometheus` datasource UID in [docs/services/grafana.md](grafana.md) — any
  dashboard panel that starts referencing Loki by UID breaks if it changes.

## Related links

- [Loki docs](https://grafana.com/docs/loki/latest/)
- [Promtail docs](https://grafana.com/docs/loki/latest/send-data/promtail/)
- [LogQL (Loki's query language)](https://grafana.com/docs/loki/latest/query/)
- [docs/services/grafana.md](grafana.md)
- [docs/services/worker.md](worker.md)
