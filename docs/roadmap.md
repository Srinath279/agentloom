# Roadmap

Planned capabilities and where they will live in the codebase. Placeholder
packages already exist under `src/agentloom/` so future work lands in a
predictable spot without another restructure.

## Sandboxing — `src/agentloom/sandbox/`

Run agent-generated code and risky tool calls in an isolated runtime
(container or microVM) with resource limits and no network by default.
Shape: a dedicated Temporal activity (`run_sandboxed`) so isolation failures
get the same retry/timeout semantics as any other activity.

## MCP tools — `src/agentloom/tools/`

Give agents tool use via MCP (Model Context Protocol) servers. Shape: each
tool invocation is an activity; tool schemas are attached to the LLM request
so the model can request calls; an MCP client manages server connections in
the worker process. The tool-use loop (model asks → activity executes →
result fed back) lives in workflow code so it is durable per step.

## Richer multi-agent patterns — `src/agentloom/workflows/`

Beyond the current fan-out → writer → critic pipeline: dynamic agent
spawning via child workflows, debate/vote patterns, and human-in-the-loop
approval via Temporal signals. Requires no new infrastructure — these are
workflow-level compositions of the existing agent template.

## Agent memory — `src/agentloom/memory/`

Persistent state across workflow runs: episodic memory (what happened in
past runs) and semantic memory (embeddings in a vector store). Shape:
read/write activities backed by a store keyed by agent + session, so
workflows stay deterministic while memory I/O happens in activities.

## LLM knowledge wiki (OKF) — `docs/` + `src/agentloom/memory/`

A curated, versioned knowledge base agents can query for grounded answers
(retrieval-augmented generation). Likely built on the same vector-store
plumbing as agent memory, with the corpus managed as markdown in-repo.

## Agent skills — `src/agentloom/skills/`

Named, reusable capabilities that bundle an `AgentSpec` with the tools and
knowledge it needs, so workflows compose skills instead of raw prompt
strings. Builds on tools + memory above.

## Sequencing

Suggested order, based on dependencies:

1. MCP tools (unlocks everything else that needs side effects)
2. Sandboxing (required before tools can run untrusted code)
3. Agent memory, then the LLM wiki on top of it
4. Agent skills (composes tools + memory)
5. Richer multi-agent patterns (continuous, as use cases appear)
