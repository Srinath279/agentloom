"""The reusable agent template and the catalog of agents used by workflows.

An agent is just data: a name, its instructions, and (optionally) a model
override. Workflows execute an agent by passing its spec to the shared LLM
activity — adding a new agent means adding a spec here and one call in a
workflow, no new activity code.

Stdlib-only (dataclasses), so this module is safe to import from workflow
code inside Temporal's deterministic sandbox.
"""

from dataclasses import dataclass

from agentloom import config


@dataclass(frozen=True)
class AgentSpec:
    """A declarative agent: what it's called and how it's instructed."""

    name: str
    instructions: str
    model: str = config.LLM_MODEL


RESEARCHER = AgentSpec(
    name="researcher",
    instructions=(
        "You are a researcher. List 3-5 key facts about the topic. "
        "Be concrete and cite well-known sources where possible."
    ),
)

CONTRARIAN_RESEARCHER = AgentSpec(
    name="contrarian-researcher",
    instructions=(
        "You are a contrarian researcher. List 3-5 common "
        "misconceptions or open questions about the topic."
    ),
)

WRITER = AgentSpec(
    name="writer",
    instructions=(
        "You are a technical writer. Weave the research notes into a "
        "clear, engaging brief of at most 200 words."
    ),
)

CRITIC = AgentSpec(
    name="critic",
    instructions=(
        "You are an exacting editor. Improve the draft for accuracy, "
        "clarity, and flow. Return only the revised text."
    ),
)

HAIKU_BOT = AgentSpec(
    name="haiku-bot",
    instructions="You only respond in haikus.",
)

CHAT_ASSISTANT = AgentSpec(
    name="chat-assistant",
    instructions=(
        "You are AgentLoom's assistant. Answer the user's latest message "
        "helpfully and concisely, using the conversation transcript for "
        "context. Reply with the assistant message only — no role prefix."
    ),
)
