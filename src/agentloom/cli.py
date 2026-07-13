"""Submit a LoomWorkflow run and print the result.

Usage:
    uv run python -m agentloom.cli "your topic here"
    # or, with the project installed:
    agentloom-run "your topic here"
"""

import asyncio
import sys
import uuid

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from agentloom import config
from agentloom.workflows import LoomWorkflow


async def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "Recursion in programming"

    client = await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
    )

    result = await client.execute_workflow(
        LoomWorkflow.run,
        topic,
        id=f"loom-{uuid.uuid4()}",
        task_queue=config.TASK_QUEUE,
    )

    print("=== Final brief ===\n")
    print(result.final)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
