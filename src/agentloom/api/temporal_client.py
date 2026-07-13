from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from agentloom import config

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(
            config.TEMPORAL_ADDRESS,
            namespace=config.TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
    return _client
