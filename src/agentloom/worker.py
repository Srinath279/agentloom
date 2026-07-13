"""Worker process: hosts the loom workflows and activities on one task queue.

Run with ``python -m agentloom.worker`` (or the ``agentloom-worker``
console script). The client uses the pydantic data converter so request/
response types serialize cleanly through Temporal.
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import Worker

from agentloom import config
from agentloom.activities import ALL_ACTIVITIES
from agentloom.workflows import ALL_WORKFLOWS

log = logging.getLogger("agentloom.worker")


def _configure_logging() -> None:
    # WORKER_LOG_FILE also feeds the local log-shipping pipeline (Alloy →
    # Loki → Grafana, see observability/alloy.alloy). In Kubernetes it stays
    # unset: logs go to stdout and the cluster's log collector picks them up.
    handlers = [logging.StreamHandler()]
    if config.WORKER_LOG_FILE:
        handlers.append(logging.FileHandler(config.WORKER_LOG_FILE))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


async def main():
    runtime = Runtime(
        telemetry=TelemetryConfig(
            metrics=PrometheusConfig(bind_address=config.WORKER_METRICS_ADDRESS)
        )
    )
    client = await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
        runtime=runtime,
    )

    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=ALL_WORKFLOWS,
        activities=ALL_ACTIVITIES,
    )
    log.info(
        "worker starting: %d workflows, %d activities on %s",
        len(ALL_WORKFLOWS),
        len(ALL_ACTIVITIES),
        config.TASK_QUEUE,
    )
    await worker.run()


def run() -> None:
    _configure_logging()
    asyncio.run(main())


if __name__ == "__main__":
    run()
