"""Unit tests for the LLM activity — no Temporal server, no real API.

ActivityEnvironment runs the activity function directly while still
providing activity.info(), heartbeats, and cancellation semantics.
The Claude HTTP call is faked by monkeypatching httpx.AsyncClient.
"""

import httpx
import pytest
from temporalio.testing import ActivityEnvironment

from activities import openai_responses
from activities.openai_responses import LLMResponsesRequest, _claude_output_text


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(openai_responses.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


async def test_create_returns_output_text(fake_llm):
    fake_llm.payload = {"output_text": "line one\nline two"}

    env = ActivityEnvironment()
    result = await env.run(
        openai_responses.create,
        LLMResponsesRequest(model="test-model", instructions="Be brief.", input="hi"),
    )

    assert result == "line one\nline two"
    sent = fake_llm.last_request["json"]
    assert sent["model"] == "test-model"
    assert "Be brief." in sent["input"] and "hi" in sent["input"]


async def test_create_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    env = ActivityEnvironment()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await env.run(
            openai_responses.create,
            LLMResponsesRequest(model="m", instructions="i", input="x"),
        )


async def test_create_raises_on_unparseable_response(fake_llm):
    fake_llm.payload = {"something": "unexpected"}

    env = ActivityEnvironment()
    with pytest.raises(RuntimeError, match="Unexpected Claude response format"):
        await env.run(
            openai_responses.create,
            LLMResponsesRequest(model="m", instructions="i", input="x"),
        )


def test_claude_output_text_parses_output_list():
    data = {
        "output": [
            {"type": "output_text", "text": "a"},
            {"content": [{"type": "output_text", "text": "b"}]},
        ]
    }
    assert _claude_output_text(data) == "ab"


def test_claude_output_text_empty_on_unknown_shape():
    assert _claude_output_text({"foo": "bar"}) == ""
