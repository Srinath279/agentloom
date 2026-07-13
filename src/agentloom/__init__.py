"""AgentLoom: durable multi-agent workflows woven together with Temporal.

Package layout:

- ``config``     — all environment-driven settings in one place
- ``agents``     — declarative agent templates (instructions + model)
- ``activities`` — non-deterministic work (LLM calls); runs outside the sandbox
- ``workflows``  — deterministic orchestration of agents
- ``worker``     — the process that hosts workflows + activities
- ``api``        — FastAPI control plane for the chat UI
- ``cli``        — submit a workflow run from the command line

Planned extension points (empty packages today, see docs/roadmap.md):
``tools`` (MCP), ``memory``, ``skills``.
"""

__version__ = "0.1.0"
