"""Central configuration for AgentLoom.

Every environment-driven setting lives here so worker, workflows, CLI, and
deploy manifests agree on names and defaults. Stdlib-only on purpose: this
module is imported from workflow code, which runs inside Temporal's
deterministic sandbox and rejects modules with I/O side effects.

The same knobs are used everywhere:
- locally, values come from `.env` (sourced by the Flox activate hook);
- on Kubernetes, from the `agentloom-config` ConfigMap and
  `agentloom-secrets` Secret (see deploy/k8s/).
"""

import os
from datetime import timedelta

# --- Temporal ---------------------------------------------------------------
TASK_QUEUE = "agentloom-task-queue"
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

# --- Worker -----------------------------------------------------------------
# Prometheus scrape endpoint for Temporal SDK metrics. Bind to 0.0.0.0 in
# Kubernetes so the scraper can reach it from outside the pod.
WORKER_METRICS_ADDRESS = os.environ.get("WORKER_METRICS_ADDRESS", "127.0.0.1:9464")
# When set, worker logs are also written to this file (tailed by Alloy → Loki
# in the local stack; unnecessary in Kubernetes where stdout is collected).
WORKER_LOG_FILE = os.environ.get("WORKER_LOG_FILE")

# --- LLM --------------------------------------------------------------------
# Any OpenAI-compatible chat-completions endpoint. Default is OpenRouter;
# point LLM_BASE_URL at e.g. Ollama (http://localhost:11434/v1/chat/completions)
# to run against a local model, in which case no API key is needed.
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "anthropic/claude-haiku-4.5")
# Local models on CPU/GPU are far slower per token than a hosted API.
LLM_ACTIVITY_TIMEOUT = timedelta(
    seconds=int(os.environ.get("LLM_ACTIVITY_TIMEOUT_SECONDS", "180"))
)

# --- Sandboxes ----------------------------------------------------------------
# Ephemeral compute for agent shell commands (agentloom.sandbox). The default
# local-docker provider runs sandboxes as containers of this image.
SANDBOX_DOCKER_IMAGE = os.environ.get("SANDBOX_DOCKER_IMAGE", "python:3.12-slim")
# Per-operation activity timeout (provision, suspend, resume, snapshot, stop).
SANDBOX_OPERATION_TIMEOUT = timedelta(
    seconds=int(os.environ.get("SANDBOX_OPERATION_TIMEOUT_SECONDS", "600"))
)
# End-to-end timeout for a command (includes a possible transparent resume).
SANDBOX_COMMAND_TIMEOUT = timedelta(
    seconds=int(os.environ.get("SANDBOX_COMMAND_TIMEOUT_SECONDS", "1200"))
)
# A sandbox idle longer than this is auto-suspended (per-sandbox override via
# Sandbox.create(idle_timeout_seconds=...); -1 there disables it).
SANDBOX_IDLE_TIMEOUT_SECONDS = float(os.environ.get("SANDBOX_IDLE_TIMEOUT_SECONDS", "300"))
