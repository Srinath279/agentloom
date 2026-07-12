# Prometheus

## What it is

[Prometheus](https://prometheus.io) is the metrics collector for the stack.
It scrapes (pulls) time-series metrics over HTTP from Temporal server and the
AgentLoom worker every 10 seconds, and stores them locally for Grafana to
query.

Config: [`observability/prometheus.yml`](../../observability/prometheus.yml)

```yaml
scrape_configs:
  - job_name: temporal-server
    static_configs: [{ targets: ["localhost:9091"] }]
  - job_name: agentloom-worker
    static_configs: [{ targets: ["localhost:9464"] }]
  - job_name: prometheus
    static_configs: [{ targets: ["localhost:9090"] }]
```

Declared as the `prometheus` service in
[`.flox/env/manifest.toml`](../../.flox/env/manifest.toml), serving on
`localhost:9090`, with its TSDB persisted to
`$FLOX_ENV_CACHE/prometheus-data`.

## Why we need it

Temporal server and the worker each expose raw Prometheus-format metrics
(`:9091` and `:9464` respectively), but nothing collects or stores them
without a scraper — you'd only ever see a live snapshot via `curl`. Prometheus
is what turns those endpoints into queryable history, which is what Grafana's
dashboards (see [docs/services/grafana.md](grafana.md)) are built on top of.

## How to use it effectively

**Query directly** at <http://localhost:9090> — useful for one-off checks or
building a new dashboard panel before committing it to Grafana. Try:

```promql
temporal_activity_execution_latency_bucket
temporal_workflow_completed_total
up
```

**Check scrape health:** <http://localhost:9090/targets> — if a target shows
`DOWN`, that service either isn't running (`flox services status`) or isn't
listening on the port Prometheus expects.

**Add a new scrape target** (e.g. a second worker instance, or a new
service's metrics endpoint): add a `job_name`/`targets` block to
`observability/prometheus.yml`; Prometheus re-reads config on restart
(`flox services restart prometheus`).

## Best practices

- **Scrape interval is a tradeoff, not a default to leave unexamined.** `10s`
  here is fine for local dev; a longer interval reduces storage/CPU at the
  cost of metric resolution — reconsider before reusing this config anywhere
  metrics volume matters.
- **Don't point Grafana panels at raw counters when a rate makes more sense.**
  Most Temporal metrics are counters/histograms — use `rate(...)` /
  `histogram_quantile(...)` in PromQL, not raw values, or dashboards will show
  meaningless ever-increasing lines.
- **This is a single, unclustered, local-disk Prometheus.** Fine for
  dev/debugging; not a substitute for a real metrics backend (with
  retention/HA/alerting policy) in production.
- **Keep job names stable.** Grafana dashboards here (`temporal-server.json`,
  `temporal-sdk.json`) query by label, including `job`; renaming a
  `job_name` in `prometheus.yml` without updating the dashboards breaks their
  panels silently (they'll just show "No data").

## Related links

- [Prometheus docs](https://prometheus.io/docs/introduction/overview/)
- [PromQL basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Temporal server metrics reference](https://docs.temporal.io/references/server-metrics)
- [Temporal SDK metrics reference](https://docs.temporal.io/references/sdk-metrics)
