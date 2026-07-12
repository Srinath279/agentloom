# Grafana

## What it is

[Grafana](https://grafana.com) is the dashboarding layer over Prometheus's
metrics — where you actually *look* at Temporal server and worker health,
rather than querying PromQL by hand.

Declared as the `grafana` service in
[`.flox/env/manifest.toml`](../../.flox/env/manifest.toml), serving on
`localhost:3000` with **anonymous admin access enabled** (`GF_AUTH_ANONYMOUS_ENABLED=true`,
`GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`) — no login needed for local dev.

Auto-provisioned on startup from
[`observability/grafana/provisioning/`](../../observability/grafana/provisioning/):

- **Datasource** (`datasources/prometheus.yml`) — points at
  `http://localhost:9090`, set as default.
- **Dashboard provider** (`dashboards/provider.yml`) — loads every dashboard
  JSON from `observability/grafana/dashboards/` into a "Temporal" folder,
  polling for changes every 30s.

Two dashboards ship today:
[`temporal-server.json`](../../observability/grafana/dashboards/temporal-server.json)
(server-side actions, task queue, persistence) and
[`temporal-sdk.json`](../../observability/grafana/dashboards/temporal-sdk.json)
(worker-side: activity execution latency, poller status, sticky cache).

## Why we need it

Prometheus stores metrics; Grafana is what makes them legible — at a glance,
"is my worker keeping up with the task queue, are activities retrying more
than expected, is workflow latency creeping up." Provisioning the datasource
and dashboards from files (rather than clicking through Grafana's UI) means
the dashboards are versioned in the repo and identical for every contributor,
with zero manual setup after `flox services start`.

## How to use it effectively

**Open it:** <http://localhost:3000> → Dashboards → Temporal folder.

**During a test run**, watch `temporal-sdk.json` for activity latency and
retry counts while `start_workflow.py` runs — you'll see the researcher
activities' concurrent execution and each subsequent step's latency in real
time.

**Add a new panel:** either edit in the Grafana UI and export the dashboard
JSON back into `observability/grafana/dashboards/` (so it's picked up by
provisioning and persists across a clean `.flox/cache` wipe), or hand-edit the
JSON directly.

**Debug "No data" panels:** check
[Prometheus's targets page](http://localhost:9090/targets) first — a Grafana
panel showing nothing almost always means the underlying Prometheus scrape is
down, not a Grafana problem.

## Best practices

- **Treat dashboard JSON as provisioned config, not UI-editing state.**
  Changes made in the Grafana UI to a file-provisioned dashboard can be
  overwritten on the next provisioning sync unless exported back to the JSON
  file — export before you lose edits.
- **Anonymous admin access is a local-dev convenience, not a production
  posture.** Never carry `GF_AUTH_ANONYMOUS_ORG_ROLE=Admin` into any
  deployment reachable outside your own machine.
- **Keep the datasource UID stable** (`uid: prometheus` in
  `datasources/prometheus.yml`) — dashboard JSON panels reference datasources
  by UID; changing it breaks every panel until they're repointed.
- **One folder per logical source of dashboards.** The `provider.yml`
  convention here (`folder: Temporal`) makes it easy to later add e.g. a
  `folder: Langfuse` provider for LLM-cost dashboards without mixing concerns
  in one folder.

## Related links

- [Grafana docs](https://grafana.com/docs/grafana/latest/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Grafana dashboard JSON model](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/view-dashboard-json-model/)
- [Temporal + Grafana/Prometheus guide](https://docs.temporal.io/self-hosted-guide/monitoring)
