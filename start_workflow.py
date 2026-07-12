"""Submit a LoomWorkflow run and print the result.

Usage:
    uv run python -m start_workflow "your topic here"
"""

import asyncio
import os
import sys
import uuid

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from workflows.loom_workflow import LoomWorkflow

TASK_QUEUE = "agentloom-task-queue"


async def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "Recursion in programming"

    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        data_converter=pydantic_data_converter,
    )

    result = await client.execute_workflow(
        LoomWorkflow.run,
        topic,
        id=f"loom-{uuid.uuid4()}",
        task_queue=TASK_QUEUE,
    )

    print("=== Final brief ===\n")
    print(result.final)


if __name__ == "__main__":
    asyncio.run(main())
