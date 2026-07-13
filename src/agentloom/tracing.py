"""How LLM calls are captured in Langfuse — defined once, used everywhere.

The shared activity ``agentloom.activities.llm`` wraps its HTTP call in
:func:`llm_generation`, so every call shows up in Langfuse the same way.

Convention: ``session_id`` = Temporal workflow ID, trace name = workflow
type. Temporal may retry an activity on any worker process, so "one trace
per run" can't be built from process-local state — deriving the session from
``activity.info()`` means every attempt of every LLM call in a workflow run
lands in the same Langfuse session, regardless of which worker executed it.
"""

from contextlib import contextmanager

from langfuse import get_client, propagate_attributes
from temporalio import activity

TAGS = ["temporal", "agentloom"]


def _activity_attribution() -> tuple[str | None, dict, dict]:
    """(observation name, propagate_attributes kwargs, metadata) for the
    current Temporal activity — empty-ish when called outside one."""
    if not activity.in_activity():
        return None, {"trace_name": "adhoc"}, {}
    info = activity.info()
    name = f"{info.workflow_type}.{info.activity_type}"
    attrs = {"session_id": info.workflow_id, "trace_name": info.workflow_type}
    metadata = {
        "workflow_id": info.workflow_id,
        "run_id": info.workflow_run_id,
        "activity_id": info.activity_id,
        "attempt": info.attempt,
        "task_queue": info.task_queue,
    }
    return name, attrs, metadata


@contextmanager
def llm_generation(*, model: str, input, name: str | None = None):
    """One Langfuse generation around one LLM call.

    Yields the generation handle — call ``gen.update(output=...)`` with the
    result. Exceptions mark the generation ``ERROR`` and re-raise, so failed
    calls are visible in Langfuse, not just in Temporal history.
    """
    langfuse = get_client()
    activity_name, attrs, metadata = _activity_attribution()
    with propagate_attributes(tags=TAGS, **attrs):
        with langfuse.start_as_current_observation(
            name=activity_name or name or "llm-call",
            as_type="generation",
            model=model,
            input=input,
            metadata=metadata,
        ) as generation:
            try:
                yield generation
            except Exception as e:
                generation.update(level="ERROR", status_message=str(e))
                raise


