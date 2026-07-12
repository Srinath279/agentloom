# Flox

## What it is

[Flox](https://flox.dev) is the environment and service manager for this
project. It replaces the usual pile of "install these system packages, run
these five commands in five terminals" setup instructions with one declarative
manifest: [`.flox/env/manifest.toml`](../../.flox/env/manifest.toml).

It does two jobs here:

1. **Reproducible dev environment.** `[install]` pins `python3`,
   `temporal-cli`, `grafana`, and `prometheus` as Nix-backed packages (no
   system-wide installs, no version drift between machines). An `on-activate`
   hook creates a project-local Python venv and `pip install -e .`s the repo
   into it.
2. **Service orchestration.** `[services]` declares every long-running process
   this project needs — `temporal`, `worker`, `prometheus`, `grafana`,
   `langfuse` — as named services with their own start command, so they can
   be started/stopped/monitored as a group or individually.

## Why we need it

Without Flox, "spin up the stack" means separately installing Temporal CLI,
Prometheus, and Grafana, remembering five different flag combinations, and
manually sequencing them (the worker must not start before Temporal is
healthy; Grafana needs specific env vars pointing at the provisioning
directory). Flox encodes all of that once, in the repo, so it's the same for
every contributor and CI can use the identical definition.

## How to use it effectively

**Enter the environment:**

```sh
flox activate
```

This runs the `on-activate` hook (creates/updates the venv, installs deps) and
drops you into a shell with `python3`, `temporal-cli`, `grafana`, and
`prometheus` on `PATH`.

**Start every service and activate in one step:**

```sh
flox activate --start-services
```

**Manage services from another terminal** (or the same one, after
activating):

```sh
flox services start            # start all services
flox services start worker     # start just one
flox services stop              # stop all
flox services status            # see what's running
flox services logs worker --follow   # tail a service's logs
```

**Where things live:** service data/logs go under `$FLOX_ENV_CACHE` (see
`.flox/cache/` — Temporal's SQLite db, Grafana's data dir, Prometheus's TSDB).
This is why restarting the environment doesn't lose your Temporal workflow
history or Grafana dashboards edits.

## Best practices

- **Don't hand-run the tools Flox manages.** If `temporal server start-dev` or
  `grafana server` is already declared as a service, starting a second copy
  outside Flox just fights over ports. Use `flox services start <name>`.
- **Put ports and paths in the manifest, not in your shell history.** If you
  need a new env var available to services, add it under `[vars]` rather than
  exporting it ad hoc — otherwise service restarts (e.g. via `flox services
  restart`) silently lose it.
- **Service commands should wait on their dependencies, not assume ordering.**
  See how `services.worker` polls `temporal operator cluster health` before
  launching `worker.py` — Flox starts services concurrently, it does not
  infer a dependency graph for you.
- **Treat `.flox/cache/` as disposable state, not source.** It's local dev
  data (Temporal's dev-server DB, Grafana/Prometheus data dirs) — safe to
  delete for a clean slate, never something to hand-edit or commit meaningful
  changes into.

## Related links

- [Flox docs](https://flox.dev/docs/)
- [Flox manifest reference](https://flox.dev/docs/reference/command-reference/manifest.toml/)
- [Flox services reference](https://flox.dev/docs/concepts/services/)
- Project manifest: [`.flox/env/manifest.toml`](../../.flox/env/manifest.toml)
