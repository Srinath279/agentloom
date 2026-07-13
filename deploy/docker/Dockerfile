# AgentLoom worker image.
# Build from the repo root:  docker build -f deploy/docker/Dockerfile -t agentloom-worker .
# The same image runs the CLI:  docker run --rm agentloom-worker agentloom-run "topic"

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies first so they cache independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY README.md ./
RUN uv sync --frozen --no-dev


FROM python:3.12-slim

RUN groupadd --system agentloom && useradd --system --gid agentloom agentloom

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

USER agentloom

# Temporal SDK Prometheus metrics (WORKER_METRICS_ADDRESS=0.0.0.0:9464 in k8s).
EXPOSE 9464

CMD ["agentloom-worker"]
