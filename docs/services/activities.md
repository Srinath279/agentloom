# Activities (`activities/openai_responses.py`)

## What it is

The single Temporal **activity** every agent in AgentLoom calls:
`openai_responses.create`. It takes an `LLMResponsesRequest` (`model`,
`instructions`, `input`), makes a direct HTTPS call to the Anthropic API, and
returns the response text as a plain `str`. It also wraps the call in a
Langfuse `generation` span for tracing.

```python
@dataclass
class LLMResponsesRequest:
    model: str
    instructions: str
    input: str

@activity.defn
async def create(request: LLMResponsesRequest) -> str:
    ...
```

Despite the filename, this is provider-agnostic in shape: any HTTP-calling
LLM activity would follow the same pattern (dataclass request in, `str` out,
Langfuse span around it).

## Why we need it

This is the module where Temporal's determinism boundary is crossed
deliberately: an *activity* is the only place non-deterministic, real-world
side effects (network calls, non-reproducible responses) are allowed to
happen. Every workflow in this repo (`HelloWorld`, `LoomWorkflow`) delegates
all actual LLM calls here rather than doing it inline, which is what makes the
workflow code itself deterministic and replay-safe. It's written once and
reused by every agent — researcher, writer, critic — so adding an agent never
means writing new I/O code, only new `instructions` text in a workflow.

## How it works

1. Reads `ANTHROPIC_API_KEY` from the environment; raises immediately if
   missing (a clear, activity-level failure rather than a cryptic HTTP 401).
2. Opens a Langfuse observation (`start_as_current_observation(...,
   as_type="generation")`), tagged with the owning workflow's ID as
   `session_id` — this is what makes every agent step of one workflow run
   show up as a single trace in Langfuse, regardless of which worker process
   or retry attempt executed it (see [docs/services/langfuse.md](langfuse.md)).
3. Calls the Anthropic API directly via `httpx.AsyncClient(timeout=15.0)` —
   note the **short client-side timeout** and **no client-side retries**.
4. Parses the response defensively (`_claude_output_text`) across a few
   possible response shapes, and raises `RuntimeError` if none match, so a
   format change fails loudly instead of returning an empty string.
5. On any exception, marks the Langfuse generation as an error before
   re-raising — so failed calls are visible in Langfuse, not just in Temporal
   history.

## How to use it effectively

**Reuse it, don't fork it.** To add a new agent, call
`self._agent(instructions, input)` in a workflow (see
[docs/services/workflows.md](workflows.md)) rather than writing a new
activity — the instructions string *is* the agent definition.

**Add a new provider alongside it, don't branch inside it.** The README's
guidance holds: drop a sibling module (e.g. `activities/openai_chat.py`) with
its own `create`-style activity and request dataclass, and register it in
`worker.py`. Keeps each activity's retry/timeout/parsing semantics
independent per provider.

**Tune the timeout at the workflow call site, not here.** The 15s httpx
timeout is a *safety net* inside the activity; the timeout that actually
governs retries is `start_to_close_timeout` passed by the calling workflow
(currently 30–60s). If you see activities timing out under load, look at both.

## Best practices

- **Never let an SDK/HTTP client retry on top of Temporal.** If you add a new
  provider's official SDK here, disable its built-in retries (as the OpenAI
  SDK previously was here via `max_retries=0`) — double retry layers make
  backoff and failure semantics unpredictable and can multiply spend.
- **Fail loudly on unexpected shapes.** `_claude_output_text` raising
  `RuntimeError(f"Unexpected Claude response format: {data}")` rather than
  silently returning `""` is deliberate — a silent empty string would
  propagate into the pipeline as a plausible-looking (wrong) result.
- **Keep secrets in the activity, never in the workflow.** `ANTHROPIC_API_KEY`
  is read here, not passed through workflow arguments — workflow arguments
  are persisted in plaintext in Temporal's event history.
- **One generation per LLM call, one session per workflow run.** If you add
  fields to the Langfuse metadata, keep including `workflow_id`/`run_id`/
  `activity_id`/`attempt` — they're what make a failed-then-retried activity
  traceable back to a specific Temporal history event.

## Related links

- [Temporal Python SDK: Activities](https://docs.temporal.io/develop/python/core-application#develop-activities)
- [Langfuse Python SDK: Generations](https://langfuse.com/docs/sdk/python/sdk-v3)
- [httpx async client](https://www.python-httpx.org/async/)
- Tests: [`tests/test_activities.py`](../../tests/test_activities.py)
