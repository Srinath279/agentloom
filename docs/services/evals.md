# Evals — agent quality gates (agent-evals)

AgentLoom's workflows are evaluated with
[agent-evals](https://github.com/Srinath279/agent-evals), installed as an
editable library (`uv add --editable`). Everything runs on the same local
stack: the eval invokes the **real `LoomWorkflow`** through Temporal, the
judge is the **local Ollama model** via its OpenAI-compatible endpoint (free),
and **Langfuse is the system of record** — golden datasets, judge rubrics
(Prompt Management), and every metric written back as scores on real traces.

## Layout

```
evals/
├── loom_task.py            task_fn: agent-evals -> Temporal -> LoomWorkflow -> Trace
│                           (opens one Langfuse trace per eval execution;
│                            session_id = workflow ID, same as agentloom.tracing)
├── custom_evaluators.py    word_count_range — the extension pattern
├── golden_loom.jsonl       3 golden topics (mirrored to Langfuse dataset
│                           `loom-brief-golden-v1` via seed-dataset)
├── golden_loom_smoke.jsonl 1-case set for the Temporal-workflow path
├── loom_brief.yaml         the eval config (judge, evaluators, gate)
└── loom_brief_smoke.yaml   smoke variant
```

## Running (inside `flox activate`, with the stack up)

```sh
# one-time seeding
uv run evals push-rubrics --config evals/loom_brief.yaml    # rubrics -> Langfuse Prompt Management
uv run evals seed-dataset --config evals/loom_brief.yaml    # golden set -> Langfuse dataset

# the gate — exit 1 on failure; report/manifest/scores under evals/runs/
uv run evals run --config evals/loom_brief.yaml --out evals/runs --post-scores

# regression gating against a promoted baseline
uv run evals promote-baseline --config evals/loom_brief.yaml --run evals/runs/<dir> --baselines evals/baselines
uv run evals run --config evals/loom_brief.yaml --out evals/runs --baselines evals/baselines
```

## What gets measured

`goal_success` (LLM judge — rubric served from **Langfuse Prompt Management**,
version-pinned so cache keys survive the storage migration) ·
`tool_called` / `tool_selection` / `steps_efficiency` (the four pipeline
stages, mapped to canonical ToolCalls) · `latency_threshold` /
`cost_threshold` · `word_count_range` (custom, brief length) ·
`forbidden_content` (no "as an AI model" boilerplate).

The judge is `provider: openai` pointed at Ollama (`OPENAI_BASE_URL` in
`.env`), with a mock fallback so runs survive Ollama being down — score
stamps always record which judge actually scored. Rubric edits belong in
Langfuse PM; editing there creates a new version and correctly invalidates
the score cache.

## The Temporal path (durable eval runs)

The same run executes as a durable `EvalRunWorkflow` on the shared dev
server — agent-evals' worker listens on the `agent-evals` task queue while
the agentloom worker serves the underlying LoomWorkflow calls:

```sh
uv run python -m agent_evals.pipelines.worker &        # eval worker
temporal workflow execute --type EvalRunWorkflow --task-queue agent-evals \
  --workflow-id loom-eval-smoke \
  -i '"evals/loom_brief_smoke.yaml"' -i 1 -i '"evals/runs"'
```

Watch it in the Temporal UI (<http://localhost:8233>): the eval workflow's
`score_case` activities and the nested `eval-loom-*` LoomWorkflow runs.
In Langfuse (<http://localhost:3001>): the `LoomEval` trace per execution,
its session containing the four agent generations, and the eval scores
attached to the trace.

## Where this goes next

Per the [master plan](https://github.com/Srinath279/agent-eval-notes): judge
calibration against human labels (`evals calibrate`), annotation queues,
online sampling of production traces (`TraceScoreWorkflow`), red-team suites
(`gate_mode: all`), and CI wiring (`evals run --baselines` as the PR gate).
