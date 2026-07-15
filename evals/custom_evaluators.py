"""AgentLoom-specific evaluators — registered on import (loom_task imports
this module, so any config using evals.loom_task gets them for free).

This is the extension pattern: subclass BaseEvaluator, @register, add a
row to agent-evals' metrics.md in the same PR."""

from __future__ import annotations

from typing import Optional

from agent_evals.core.evaluator import BaseEvaluator, register
from agent_evals.core.schemas import Case, Score, Trace


@register
class WordCountRangeEvaluator(BaseEvaluator):
    """word_count_range — deterministic. The configured output field must
    land inside [min_words, max_words]: too short = lazy brief, too long =
    the critic didn't cut."""

    name = "word_count_range"
    level = "output"

    def evaluate(self, trace: Trace, case: Optional[Case] = None) -> Score:
        field = self.params.get("field", "final")
        min_words = self.params.get("min_words", 1)
        max_words = self.params.get("max_words", 10_000)

        text = trace.output.get(field, "") if isinstance(trace.output, dict) else str(trace.output)
        words = len(str(text).split())
        ok = min_words <= words <= max_words
        return Score(
            name=self.name,
            value=1.0 if ok else 0.0,
            level=self.level,
            comment=f"{words} words (allowed {min_words}-{max_words})",
        )
