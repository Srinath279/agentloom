"""Non-deterministic work (LLM calls) executed outside the workflow sandbox.

``ALL_ACTIVITIES`` is the single registration list the worker uses; add new
activities here and they are picked up automatically.
"""

from agentloom.activities import llm

ALL_ACTIVITIES = [llm.run_llm]

__all__ = ["llm", "ALL_ACTIVITIES"]
