# Workflows (`src/agentloom/workflows/`)

## What it is

The orchestration layer — plain Python classes decorated with
`@workflow.defn` that describe *what agents run, in what order, with what
data flowing between them*. Two workflows exist today:

- **`HelloWorld`** (`src/agentloom/workflows/hello_world.py`) — one activity call,
  a haiku bot. The minimal example of "a workflow."
- **`LoomWorkflow`** (`src/agentloom/workflows/loom.py`) — the actual multi-agent
  pipeline:

  ```
                  ┌──────────────────┐
          ┌──────▶│ Researcher (facts)│──┐
   topic ─┤       └──────────────────┘  ├──▶ Writer ──▶ Critic ──▶ final brief
          │       ┌──────────────────┐  │
          └──────▶│ Researcher       │──┘
                  │ (misconceptions) │
                  └──────────────────┘
  ```

  Two researcher activities fan out in parallel via `asyncio.gather`, a
  writer agent weaves their notes into a draft, and a critic agent produces
  the final version. Every agent is the *same* underlying activity
  (`llm.run_llm`) called with a different `AgentSpec` — a declarative
  template (name + instructions + model) from
  `src/agentloom/agents/catalog.py`. See
  [docs/services/activities.md](activities.md).

## Why we need it

This is where the "multi-agent pipeline" actually lives as a readable,
declarative shape — `asyncio.gather(...)` for parallel steps, plain
`await self._run_agent(...)` for sequential ones. Because it's real Python inside
Temporal's deterministic sandbox, the pipeline topology is versionable,
diffable, and testable the same way any other code is, while Temporal handles
everything about *durability* (crash recovery, retries, timeouts) transparently
underneath.

## How to use it effectively

**Add a new agent to the existing pipeline:** define an `AgentSpec` in
`src/agentloom/agents/catalog.py`, then add one
`self._run_agent(spec, input)` call and wire its output into the next
step — no new activity code needed (see
[docs/services/activities.md](activities.md)).

**Add a new pipeline:** define a new `@workflow.defn` class in a new file
under `src/agentloom/workflows/`, add it to `ALL_WORKFLOWS` in
`src/agentloom/workflows/__init__.py` (the worker registers that list),
and call it from a client (like `src/agentloom/cli.py` does for `LoomWorkflow`).

**Test it without hitting a real LLM:** replace the `run_llm` activity with a
scripted fake registered under the *same activity name* (`@activity.defn(name="run_llm")`)
when constructing the test `Worker` — see
[`tests/test_workflows.py`](../../tests/test_workflows.py). This runs actual
workflow scheduling/retry logic against Temporal's in-process time-skipping
test server, with zero LLM calls or network access.

**Add human-in-the-loop control:** use a
[Temporal signal](https://docs.temporal.io/develop/python/message-passing#signals)
to pause `LoomWorkflow` between the writer and critic steps for approval — the
workflow can `await workflow.wait_condition(...)` on a signal handler setting
a flag, which is itself durable (a crash while paused loses nothing).

## Best practices

- **Keep workflow code deterministic — always.** No `datetime.now()`, no
  `random`, no direct `httpx`/file I/O, no un-seeded dict/set iteration order
  dependencies. Anything like that belongs in an activity. Non-deterministic
  imports must be wrapped in `workflow.unsafe.imports_passed_through()`
  exactly as `llm` is here — importing `httpx`/`langfuse`
  directly at module scope inside a workflow file will fail sandbox checks.
- **Every `execute_activity` call needs a `start_to_close_timeout`.** Both
  workflows set one explicitly (30s for `HelloWorld`,
  `config.LLM_ACTIVITY_TIMEOUT` — 180s by default, sized for local model
  latency — for `LoomWorkflow`) — an activity call without a timeout can
  hang a workflow indefinitely.
- **Use `asyncio.gather` for true fan-out, plain `await` for dependencies.**
  `LoomWorkflow` only parallelizes the two researcher calls because neither
  depends on the other's output; the writer and critic are sequential because
  each needs the prior step's result. Don't parallelize steps that have a
  data dependency.
- **Return structured results, not just strings.** `LoomResult` (a
  `@dataclass` with `research_notes`, `draft`, `final`) makes intermediate
  state inspectable from the Temporal Web UI and from calling code — prefer
  this over collapsing everything into the final string only.
- **Model identifiers live in configuration, not activity code.** The default
  comes from `LLM_MODEL` (`src/agentloom/config.py`); an individual agent can
  override it via its `AgentSpec.model` field. Swapping models is a one-line,
  obviously-reviewable change.

## Related links

- [Temporal Python SDK: Workflows](https://docs.temporal.io/develop/python/core-application#develop-workflows)
- [Workflow determinism](https://docs.temporal.io/workflows#deterministic-constraints)
- [Signals (human-in-the-loop)](https://docs.temporal.io/develop/python/message-passing#signals)
- [Testing workflows](https://docs.temporal.io/develop/python/testing-suite)
- Tests: [`tests/test_workflows.py`](../../tests/test_workflows.py)
