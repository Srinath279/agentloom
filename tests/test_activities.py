"""Unit tests for the LLM activity — no Temporal server, no real API.

ActivityEnvironment runs the activity function directly while still
providing activity.info(), heartbeats, and cancellation semantics.
The chat-completions HTTP call is faked by monkeypatching httpx.AsyncClient.
"""

import httpx
import pytest
from temporalio.testing import ActivityEnvironment

from agentloom import config
from agentloom.activities import llm
from agentloom.activities.llm import LLMRequest, _chat_output_text


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None
            )

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; records the request it receives."""

    payload: dict = {}
    last_request: dict = {}

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).last_request = {"url": url, "json": json, "headers": headers}
        return _FakeResponse(type(self).payload)


@pytest.fixture
def fake_llm(monkeypatch):
    # Hermetic regardless of the developer's local .env (e.g. LLM_BASE_URL
    # pointed at a local Ollama server) — tests always exercise the
    # OpenRouter default path unless a test opts into overriding it.
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


async def test_run_llm_returns_output_text(fake_llm):
    fake_llm.payload = {
        "choices": [{"message": {"role": "assistant", "content": "line one\nline two"}}]
    }

    env = ActivityEnvironment()
    result = await env.run(
        llm.run_llm,
        LLMRequest(model="test-model", instructions="Be brief.", input="hi"),
    )

    assert result == "line one\nline two"
    sent = fake_llm.last_request["json"]
    assert sent["model"] == "test-model"
    assert sent["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "hi"},
    ]
    headers = fake_llm.last_request["headers"]
    assert headers["authorization"] == "Bearer test-key"
    assert fake_llm.last_request["url"] == config.DEFAULT_LLM_BASE_URL


async def test_run_llm_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    env = ActivityEnvironment()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await env.run(
            llm.run_llm,
            LLMRequest(model="m", instructions="i", input="x"),
        )


async def test_run_llm_uses_llm_base_url_without_requiring_api_key(fake_llm, monkeypatch):
    # A local model server (e.g. Ollama) needs no API key — only OpenRouter
    # (the DEFAULT_LLM_BASE_URL) does.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1/chat/completions")
    fake_llm.payload = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    env = ActivityEnvironment()
    result = await env.run(
        llm.run_llm,
        LLMRequest(model="qwen2.5:14b-instruct", instructions="i", input="x"),
    )

    assert result == "hi"
    assert fake_llm.last_request["url"] == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in fake_llm.last_request["headers"]


async def test_run_llm_raises_on_unparseable_response(fake_llm):
    fake_llm.payload = {"something": "unexpected"}

    env = ActivityEnvironment()
    with pytest.raises(RuntimeError, match="Unexpected chat completions response format"):
        await env.run(
            llm.run_llm,
            LLMRequest(model="m", instructions="i", input="x"),
        )


def test_chat_output_text_parses_message_content():
    data = {"choices": [{"message": {"role": "assistant", "content": "a b"}}]}
    assert _chat_output_text(data) == "a b"


def test_chat_output_text_empty_on_unknown_shape():
    assert _chat_output_text({"foo": "bar"}) == ""
