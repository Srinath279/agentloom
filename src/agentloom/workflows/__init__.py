"""Deterministic orchestration of agents.

``ALL_WORKFLOWS`` is the single registration list the worker uses; add new
workflows here and they are picked up automatically.
"""

from agentloom.workflows.chat import ChatWorkflow
from agentloom.workflows.hello_world import HelloWorld
from agentloom.workflows.loom import LoomResult, LoomWorkflow
from agentloom.workflows.sandbox_demo import SandboxDemoWorkflow

ALL_WORKFLOWS = [HelloWorld, LoomWorkflow, ChatWorkflow, SandboxDemoWorkflow]

__all__ = [
    "HelloWorld",
    "LoomWorkflow",
    "LoomResult",
    "ChatWorkflow",
    "SandboxDemoWorkflow",
    "ALL_WORKFLOWS",
]
