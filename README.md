# 🧵 AgentLoom

**Durable multi-agent workflows, woven together with [Temporal](https://temporal.io).**

A loom weaves independent threads into one fabric. AgentLoom does the same with
LLM agents: each agent is a thread, Temporal is the loom, and the workflow is the
fabric — durable, resumable, and observable. If a worker crashes mid-pipeline,
execution resumes exactly where it left off. No lost LLM calls, no duplicate spend.

## What's inside

| File | Purpose |
|---|---|
| `activities/openai_responses.py` | One generic LLM activity, reused by every agent |
| `workflows/hello_world_workflow.py` | Single-agent starter (haiku bot) |
| `workflows/loom_workflow.py` | Multi-agent pipeline: parallel researchers → writer → critic |
| `worker.py` | Hosts workflows + activities on the `agentloom-task-queue` |
| `start_workflow.py` | Submits a run and prints the final brief |

## Design decisions (Temporal best practices)

- **Retries belong to Temporal, not the SDK.** The OpenAI client is created with
  `max_retries=0`; Temporal's retry policy owns backoff and recovery.
- **Pydantic data converter** on both client and worker, so LLM response types
  serialize cleanly through workflow history.
- **One generic activity, many agents.** Agents differ only by their
  instructions — the pipeline stays declarative inside the workflow.
- **Parallel fan-out with `asyncio.gather`** inside the workflow: Temporal
  schedules the researcher activities concurrently and records both results
  deterministically.

## The pipeline

```
                ┌──────────────────┐
        ┌──────▶│ Researcher (facts)│──┐
 topic ─┤       └──────────────────┘  ├──▶ Writer ──▶ Critic ──▶ final brief
        │       ┌──────────────────┐  │
        └──────▶│ Researcher       │──┘
                │ (misconceptions) │
                └──────────────────┘
```

## Quick start

1. **Install dependencies** (uses [uv](https://docs.astral.sh/uv/)):

   ```sh
   uv sync
   ```

2. **Set your API key** (see `.env.example`):

   ```sh
   export ANTHROPIC_API_KEY=your_claude_api_key
   ```

3. **Start the Temporal dev server:**

   ```sh
   temporal server start-dev
   ```

4. **Run the worker** (separate terminal):

   ```sh
   uv run python -m worker
   ```

5. **Kick off a workflow** (another terminal):

   ```sh
   uv run python -m start_workflow "Vector databases"
   ```

Watch the pipeline execute step-by-step in the Temporal Web UI at
<http://localhost:8233> — kill the worker mid-run and restart it to see
durable execution pick up where it stopped.

## Extending the loom

- Add a new agent: one more `self._agent(...)` call in `loom_workflow.py`.
- Add a new provider: drop another generic activity next to
  `openai_responses.py` and register it in `worker.py`.
- Human in the loop: use Temporal signals to pause the loom for approval
  between the writer and critic steps.
