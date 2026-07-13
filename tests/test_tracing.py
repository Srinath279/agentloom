"""Tests for the shared Langfuse tracing layer.

No Langfuse server is needed — the SDK buffers/no-ops without one. These
verify the *contract*: exceptions propagate (marked as errors, not
swallowed) and the context manager works outside a Temporal activity.
"""

import pytest

from agentloom import tracing


def test_llm_generation_yields_and_updates_outside_activity():
    with tracing.llm_generation(model="m", input={"x": 1}) as gen:
        gen.update(output="done")


def test_llm_generation_reraises_exceptions():
    with pytest.raises(ValueError, match="boom"):
        with tracing.llm_generation(model="m", input="hi"):
            raise ValueError("boom")
