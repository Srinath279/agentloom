"""ChatWorkflow: a durable, interactive conversation with an agent.

Each chat session is one long-running Temporal workflow:

- user messages arrive as the ``user_message`` signal;
- the reply comes from the shared (Langfuse-traced) LLM activity;
- the full transcript lives in workflow state, queryable via ``get_history``
  — so the UI can reload it any time, and a worker crash mid-conversation
  loses nothing (the workflow resumes exactly where it was);
- ``end_chat`` completes the workflow.

The workflow consumes zero CPU while waiting for the next message.
"""

from dataclasses import dataclass, field

from temporalio import workflow

from agentloom import config
from agentloom.agents import CHAT_ASSISTANT

# The activities module imports httpx/langfuse, which the deterministic
# workflow sandbox rejects; pass it through — the workflow only needs the
# activity reference and its request dataclass.
with workflow.unsafe.imports_passed_through():
    from agentloom.activities import llm

# Keep the prompt bounded: only the most recent turns are sent to the model.
MAX_PROMPT_TURNS = 30
# Continue-as-new before Temporal's event-history limits become a concern.
MAX_TURNS_PER_RUN = 500


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ChatState:
    messages: list[ChatMessage] = field(default_factory=list)
    responding: bool = False
    ended: bool = False


@workflow.defn
class ChatWorkflow:
    def __init__(self) -> None:
        self._state = ChatState()
        self._pending: list[str] = []

    # ───── Signals / queries ─────
    @workflow.signal
    def user_message(self, text: str) -> None:
        if text and text.strip():
            self._pending.append(text.strip())

    @workflow.signal
    def end_chat(self) -> None:
        self._state.ended = True

    @workflow.query
    def get_history(self) -> ChatState:
        return self._state

    # ───── Run loop ─────
    @workflow.run
    async def run(self, system_prompt: str | None = None) -> ChatState:
        instructions = system_prompt or CHAT_ASSISTANT.instructions

        while True:
            await workflow.wait_condition(lambda: bool(self._pending) or self._state.ended)
            if self._state.ended and not self._pending:
                return self._state

            text = self._pending.pop(0)
            self._state.messages.append(ChatMessage(role="user", content=text))
            self._state.responding = True
            try:
                reply = await workflow.execute_activity(
                    llm.run_llm,
                    llm.LLMRequest(
                        model=CHAT_ASSISTANT.model,
                        instructions=instructions,
                        input=self._transcript(),
                    ),
                    start_to_close_timeout=config.LLM_ACTIVITY_TIMEOUT,
                )
                self._state.messages.append(ChatMessage(role="assistant", content=reply))
            finally:
                self._state.responding = False

            if len(self._state.messages) >= MAX_TURNS_PER_RUN:
                # Fresh history for Temporal; the transcript itself carries over.
                workflow.continue_as_new(system_prompt)

    def _transcript(self) -> str:
        """The activity takes one input string, so the recent conversation is
        rendered as a plain transcript ending at the turn to answer."""
        recent = self._state.messages[-MAX_PROMPT_TURNS:]
        lines = [f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in recent]
        lines.append("Assistant:")
        return "\n".join(lines)
