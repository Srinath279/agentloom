# Deploying to Kubernetes

The only piece of AgentLoom you deploy is the **worker** — a stateless
poller of the Temporal task queue. Temporal itself, and the observability
stack, are separate concerns (below). Because workers are stateless, scaling
is just replicas: every pod polls the same `agentloom-task-queue` and
Temporal distributes workflow/activity tasks across them.

## Layout

```
deploy/
├── docker/Dockerfile          # multi-stage build (uv), non-root, runs agentloom-worker
└── k8s/
    ├── base/                  # Deployment, metrics Service, ConfigMap
    │   └── secret.example.yaml  # template only — never commit real secrets
    └── overlays/
        ├── dev/               # namespace agentloom-dev, 1 replica, small resources
        └── prod/              # namespace agentloom-prod, 3 replicas, PDB, pinned tag
```

The same environment variables drive every environment — locally they come
from `.env` (via Flox), in-cluster from the `agentloom-config` ConfigMap and
`agentloom-secrets` Secret. The full list lives in
[`src/agentloom/config.py`](../../src/agentloom/config.py).

## 1. Build and push the image

```sh
docker build -f deploy/docker/Dockerfile -t <registry>/agentloom-worker:dev .
docker push <registry>/agentloom-worker:dev
```

Set the image name/tag per overlay in its `kustomization.yaml` (`images:`
section) — dev tracks a `dev` tag, prod pins a release tag.

## 2. Point at a Temporal server

The worker needs a reachable Temporal frontend; pick one and set
`TEMPORAL_ADDRESS` in the overlay's `configMapGenerator`:

- **In-cluster:** install the
  [Temporal Helm chart](https://github.com/temporalio/helm-charts); the
  default address in the base manifests
  (`temporal-frontend.temporal.svc.cluster.local:7233`) matches it.
- **Temporal Cloud:** `<namespace>.<account>.tmprl.cloud:7233` plus mTLS
  client certificates (mount them and extend `worker.py`'s `Client.connect`
  with TLS config — not wired up yet).
- **Local dev cluster (kind/minikube):** run `temporal server start-dev` on
  the host and expose it to the cluster, or run the dev server as a pod.

## 3. Create the secret

Secrets are intentionally not in the manifests (see
`deploy/k8s/base/secret.example.yaml`):

```sh
kubectl -n agentloom-dev create secret generic agentloom-secrets \
  --from-literal=OPENROUTER_API_KEY=sk-or-v1-...
```

Add `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` the same
way if you run a Langfuse instance the cluster can reach.

## 4. Deploy

```sh
# Dev
kubectl apply -k deploy/k8s/overlays/dev

# Prod
kubectl apply -k deploy/k8s/overlays/prod
```

Verify:

```sh
kubectl -n agentloom-dev get pods
kubectl -n agentloom-dev logs deploy/agentloom-worker -f
```

A healthy worker logs its Temporal connection and then sits polling. Submit
a workflow from anywhere that can reach the same Temporal frontend:

```sh
TEMPORAL_ADDRESS=<frontend-address> uv run python -m agentloom.cli "Vector databases"
```

## Scaling and production notes

- **Scale = replicas.** `kubectl scale deploy/agentloom-worker --replicas=N`,
  or adjust the overlay. For autoscaling, an HPA on CPU works, but the better
  signal is Temporal's task-queue backlog
  (`temporal_worker_task_slots_available` / schedule-to-start latency from
  the `:9464` metrics endpoint) via KEDA or a custom-metrics HPA.
- **Metrics.** Every pod exposes Prometheus metrics on `:9464`
  (`WORKER_METRICS_ADDRESS=0.0.0.0:9464` from the ConfigMap); the
  `agentloom-worker-metrics` Service plus the `prometheus.io/*` pod
  annotations make it scrapeable by most cluster Prometheus setups.
- **Logs.** In-cluster the worker logs to stdout only (`WORKER_LOG_FILE`
  unset) — collect them with your cluster's log pipeline; the local
  Alloy/Loki setup under `observability/` is for local dev, not the cluster.
- **Graceful shutdown.** On SIGTERM the Temporal SDK stops polling and lets
  in-flight activities finish; anything unfinished is retried on another
  worker — pod restarts and rolling deploys are safe by design.
- **Prod overlay extras:** 3 replicas, a PodDisruptionBudget
  (`minAvailable: 1`), pinned image tag, higher resource requests.
