"""Worker process: hosts the workflows and activities.

The client uses the pydantic data converter so OpenAI SDK response
types serialize cleanly through Temporal.
"""

import asyncio
import os

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import Worker

from activities import openai_responses
from workflows.hello_world_workflow import HelloWorld
from workflows.loom_workflow import LoomWorkflow

TASK_QUEUE = "agentloom-task-queue"


async def main():
    runtime = Runtime(
        telemetry=TelemetryConfig(
            metrics=PrometheusConfig(
                bind_address=os.environ.get("WORKER_METRICS_ADDRESS", "127.0.0.1:9464")
            )
        )
    )
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        data_converter=pydantic_data_converter,
        runtime=runtime,
    )

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[HelloWorld, LoomWorkflow],
        activities=[openai_responses.create],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
