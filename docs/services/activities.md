# Activities (`src/agentloom/activities/`)

## What it is

The single Temporal **activity** every agent in AgentLoom calls:
`llm.run_llm`. It takes an `LLMRequest` (`model`,
`instructions`, `input`), makes a direct HTTP(S) call to an OpenAI-compatible
Chat Completions API, and returns the response text as a plain `str`. It also
wraps the call in a Langfuse `generation` span for tracing.

The endpoint is configurable: by default it calls
[OpenRouter](https://openrouter.ai) (which proxies to Claude, e.g.
`anthropic/claude-haiku-4.5`), but setting `LLM_BASE_URL` points it at any
other OpenAI-compatible server instead — including a local one, like Ollama
running on this machine's GPU (`http://localhost:11434/v1/chat/completions`
with `LLM_MODEL=qwen2.5:14b-instruct`). No code change needed either way.

```python
@dataclass
class LLMRequest:
    model: str
    instructions: str
    input: str

@activity.defn
async def create(request: LLMRequest) -> str:
    ...
```

Despite the filename, this is provider-agnostic in shape: any HTTP-calling
LLM activity would follow the same pattern (dataclass request in, `str` out,
Langfuse span around it). Going through OpenRouter rather than calling
Anthropic directly means swapping `model` to a different provider's slug
(`openai/...`, `google/...`, etc.) is a one-line change with no code change
required.

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

1. Reads `LLM_BASE_URL` (defaults to OpenRouter's endpoint) and
   `LLM_API_KEY`/`OPENROUTER_API_KEY` from the environment. An API key is
   only required when talking to the default OpenRouter endpoint; a local
   server like Ollama needs none. Raises immediately if OpenRouter is being
   used without a key (a clear, activity-level failure rather than a cryptic
   HTTP 401).
2. Opens a Langfuse generation via `agentloom.tracing.llm_generation(...)` —
   the shared tracing layer tags it with the owning workflow's ID as
   `session_id`, which is what makes every agent step of one workflow run
   show up as a single session in Langfuse, regardless of which worker
   process or retry attempt executed it (see
   [docs/services/langfuse.md](langfuse.md)).
3. Calls `POST <LLM_BASE_URL>` directly via `httpx.AsyncClient(timeout=120.0)`
   — note **no client-side retries** — with `instructions` sent as the
   `system` message and `input` as the `user` message. The timeout is
   generous because local model inference (CPU/GPU-bound) is far slower
   per token than a hosted API.
4. Parses the response (`_chat_output_text`) — expects the standard
   OpenAI-shaped `choices[0].message.content` — and raises `RuntimeError` if
   that's missing, so a format change fails loudly instead of returning an
   empty string.
5. On any exception, `llm_generation` marks the Langfuse generation as an
   error before re-raising — so failed calls are visible in Langfuse, not
   just in Temporal history.

## How to use it effectively

**Reuse it, don't fork it.** To add a new agent, define an `AgentSpec` in
`src/agentloom/agents/catalog.py` and call `self._run_agent(spec, input)` in
a workflow (see [docs/services/workflows.md](workflows.md)) rather than
writing a new activity — the spec *is* the agent definition.

**Swap models via the `model` field, not new code.** Because this activity
speaks the OpenAI-compatible shape that both OpenRouter and local servers
like Ollama implement, changing which model an agent uses is just changing
the `model` string passed into `LLMRequest` — driven by the
`LLM_MODEL` env var (read in `src/agentloom/config.py`, overridable per
agent via `AgentSpec.model`) — plus, if switching providers, `LLM_BASE_URL`.
Check [openrouter.ai/models](https://openrouter.ai/models) or
`GET https://openrouter.ai/api/v1/models` for OpenRouter slugs, or
`ollama list` for locally-pulled model names.

**Add a genuinely different activity shape alongside it, don't branch inside
it.** If you need a provider OpenRouter doesn't proxy, or need
provider-specific features OpenRouter's OpenAI-compatible shape doesn't
expose, drop a sibling module (e.g. `src/agentloom/activities/anthropic.py`)
with its own activity and request dataclass, and add it to `ALL_ACTIVITIES`
in `src/agentloom/activities/__init__.py`. Keeps each activity's
retry/timeout/parsing semantics independent.

**Tune the timeout at the workflow call site, not here.** The 120s httpx
timeout is a *safety net* inside the activity; the timeout that actually
governs retries is `start_to_close_timeout` passed by the calling workflow
(currently 180s, sized for local model latency). If you see activities
timing out under load, look at both.

## Best practices

- **Never let an SDK/HTTP client retry on top of Temporal.** If you swap this
  for an official provider SDK, disable its built-in retries — double retry
  layers make backoff and failure semantics unpredictable and can multiply
  spend.
- **Fail loudly on unexpected shapes.** `_chat_output_text` raising
  `RuntimeError(f"Unexpected OpenRouter response format: {data}")` rather
  than silently returning `""` is deliberate — a silent empty string would
  propagate into the pipeline as a plausible-looking (wrong) result.
- **Keep secrets in the activity, never in the workflow.** `LLM_API_KEY`/
  `OPENROUTER_API_KEY` is read here, not passed through workflow arguments —
  workflow arguments are persisted in plaintext in Temporal's event history.
- **`.env` is not auto-loaded by `src/agentloom/worker.py`.** There's no dotenv dependency
  in this repo — `LLM_BASE_URL`/`LLM_MODEL`/`OPENROUTER_API_KEY` only reach
  the worker process if something sources `.env` into its environment before
  it starts. This project's Flox `on-activate` hook does that (see
  [docs/services/flox.md](flox.md)); if you run the worker outside Flox,
  you're responsible for exporting it yourself.
- **One generation per LLM call, one session per workflow run.** The
  attribution (`workflow_id`/`run_id`/`activity_id`/`attempt` metadata) is
  centralized in `agentloom.tracing` — extend it there, not per activity, so
  a failed-then-retried call stays traceable to its exact Temporal history
  event everywhere.

## Related links

- [Temporal Python SDK: Activities](https://docs.temporal.io/develop/python/core-application#develop-activities)
- [OpenRouter API reference (Chat Completions)](https://openrouter.ai/docs/api-reference/chat-completion)
- [OpenRouter model list](https://openrouter.ai/models)
- [Langfuse Python SDK: Generations](https://langfuse.com/docs/sdk/python/sdk-v3)
- [httpx async client](https://www.python-httpx.org/async/)
- Tests: [`tests/test_activities.py`](../../tests/test_activities.py)
