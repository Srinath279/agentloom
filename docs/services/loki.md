# Loki + Alloy

## What it is

[Loki](https://grafana.com/oss/loki/) is Grafana's log-aggregation
datastore — like Prometheus, but for logs instead of metrics.
[Grafana Alloy](https://grafana.com/docs/alloy/latest/) is the agent that
tails a log file and ships each line into Loki. Together they let you search
and stream the `worker` service's logs from inside Grafana instead of
`flox services logs worker -f`.

- **`loki`** (`grafana-loki` package, pinned to `3.6.8` in
  `.flox/env/manifest.toml` → `[install]` — see below) — filesystem-backed,
  single-binary mode, configured by
  [`observability/loki.yml`](../../observability/loki.yml). Listens on
  `:3100`, stores chunks/index under `$FLOX_ENV_CACHE/loki`.
- **`alloy`** (`grafana-alloy` package) — configured by
  [`observability/alloy.alloy`](../../observability/alloy.alloy), written in
  Alloy's component-based config language. Tails
  `$FLOX_ENV_CACHE/worker.log` (`local.file_match` → `loki.source.file`) and
  pushes every line to Loki's `/loki/api/v1/push` endpoint (`loki.write`),
  labeled `job=agentloom-worker`. Its own HTTP UI/API listens on `:12345`
  (`--server.http.listen-addr`), separate from anything it ships.

The worker only writes to that log file because `worker.py`'s
`_configure_logging()` adds a `logging.FileHandler` when `WORKER_LOG_FILE` is
set — which the `[services.worker]` command does, pointing it at
`$FLOX_ENV_CACHE/worker.log`.

**Why `grafana-loki` is pinned to `3.6.8`:** newer versions (3.7.x+) dropped
the bundled `promtail` binary from that package's outputs, and this project
migrated off Promtail to Alloy anyway (Promtail is Grafana's deprecated log
shipper, in maintenance mode). The pin is just to keep a known-good Loki
version; it's unrelated to the shipping agent itself.

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

**Why Alloy, not Promtail:** Promtail is Grafana Labs' deprecated log
shipper — in maintenance mode, superseded by Alloy as the single unified
telemetry collector (logs, metrics, traces, profiles) going forward. Alloy is
where new features and fixes land; a fresh setup has no reason to start on
the deprecated path.

## How to use it effectively

**View live logs:** Grafana (<http://localhost:3000>) → Explore → select the
`Loki` datasource → query `{job="agentloom-worker"}`. Add `|= "ERROR"` (LogQL
line filter) to narrow to failures, e.g. while chasing the stuck-activity
retries described in [docs/services/activities.md](activities.md).

**Correlate with a workflow run:** every activity failure logged by the
Temporal SDK includes the `workflow_id` in its message — search
`{job="agentloom-worker"} |= "loom-<id>"` to pull just that run's lines out of
the interleaved stream.

**Inspect Alloy itself:** its UI at <http://localhost:12345> shows each
component's live state (`local.file_match.worker_log`,
`loki.source.file.worker`, `loki.write.local`) — useful for confirming the
file is actually being tailed before suspecting Loki.

**Add more log sources:** add another `local.file_match` /
`loki.source.file` pair in `observability/alloy.alloy`, forwarding to the
same `loki.write.local.receiver` with a distinguishing label — don't spin up
a second Alloy service for it.

## Best practices

- **The log file is derived state, not source of truth.** `worker.log` lives
  under `$FLOX_ENV_CACHE`, same as `temporal.db` and `prometheus-data` — it's
  gitignored and safe to delete; Loki/Alloy will just start fresh.
- **`env(...)` in `alloy.alloy` resolves at Alloy startup**, same role as
  `-config.expand-env=true` on `loki.yml` — both need `$FLOX_ENV_CACHE` set in
  the environment before the service starts, which Flox already guarantees.
- **Keep the datasource UID (`loki`) stable**, same reasoning as the
  `prometheus` datasource UID in [docs/services/grafana.md](grafana.md) — any
  dashboard panel that starts referencing Loki by UID breaks if it changes.

## Related links

- [Loki docs](https://grafana.com/docs/loki/latest/)
- [Grafana Alloy docs](https://grafana.com/docs/alloy/latest/)
- [Alloy config language reference](https://grafana.com/docs/alloy/latest/reference/config-blocks/)
- [LogQL (Loki's query language)](https://grafana.com/docs/loki/latest/query/)
- [docs/services/grafana.md](grafana.md)
- [docs/services/worker.md](worker.md)
