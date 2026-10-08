import asyncio
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from diagagent import cli
from diagagent.llm import LLMError, LLMRequest, Message, ToolCall, ToolSpec, make_provider
from diagagent.llm.anthropic_chat import AnthropicProvider, to_native_messages

from test_agent import _load_with_runs, only


def _message(content, stop_reason="end_turn"):
    return BetaMessage.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900,
                  "cache_creation_input_tokens": 0}})


THINKING = {"type": "thinking", "thinking": "", "signature": "sig-1"}


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **params):
        self.calls.append(params)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(responses):
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages), messages=messages), messages


def test_request_translation():
    client, fake = _client([_message([
        THINKING,
        {"type": "text", "text": "Je regarde la fiche."},
        {"type": "tool_use", "id": "toolu_1", "name": "get_ci", "input": {"id_or_hostname": "srv-pay-01"}},
    ], "tool_use")])
    provider = AnthropicProvider(client, "claude-opus-5-5")
    resp = provider.complete(LLMRequest(
        system="sys", reasoning="high", max_tokens=4000,
        messages=[Message("user", "q")],
        tools=[ToolSpec("get_ci", "Fiche CI", {"type": "object", "properties": {}})]))

    p = fake.calls[0]
    assert p["model"] == "claude-opus-5-5" and p["system"] == "sys"
    assert p["max_tokens"] == 16_000 and p["thinking"] == {"type": "adaptive"}
    assert p["output_config"] == {"effort": "high"} and p["cache_control"] == {"type": "ephemeral"}
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    assert p["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert resp.stop_reason == "tool_call" and resp.text == "Je regarde la fiche."
    assert resp.tool_calls == [ToolCall("toolu_1", "get_ci", {"id_or_hostname": "srv-pay-01"})]
    assert resp.usage.input_tokens == 1000 and resp.usage.output_tokens == 20
    assert resp.native[0] == THINKING


def test_history_keeps_thinking_and_groups_tool_results():
    native = [THINKING, {"type": "tool_use", "id": "a", "name": "x", "input": {}},
              {"type": "tool_use", "id": "b", "name": "y", "input": {}}]
    out = to_native_messages([
        Message("user", "q"),
        Message("assistant", "", [ToolCall("a", "x", {}), ToolCall("b", "y", {})], native=native),
        Message("tool", "r1", tool_call_id="a"),
        Message("tool", "", tool_call_id="b"),
        Message("user", "Budget atteint"),
    ])
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[1]["content"] == native
    assert out[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "a", "content": "r1"},
        {"type": "tool_result", "tool_use_id": "b", "content": "(vide)"},
        {"type": "text", "text": "Budget atteint"},
    ]
    # Un tour venu d'un autre fournisseur (sans contenu natif) est reconstruit.
    rebuilt = to_native_messages([Message("assistant", "t", [ToolCall("a", "x", {"k": 1})])])
    assert rebuilt[0]["content"] == [{"type": "text", "text": "t"},
                                     {"type": "tool_use", "id": "a", "name": "x", "input": {"k": 1}}]


def test_refusal_and_errors():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    client, _ = _client([
        _message([{"type": "tool_use", "id": "t", "name": "x", "input": {}}], "refusal"),
        anthropic.RateLimitError("lent", response=httpx2.Response(429, request=request), body=None),
        anthropic.BadRequestError("invalide", response=httpx2.Response(400, request=request), body=None),
    ])
    provider = AnthropicProvider(client, "claude-opus-5-5", fallbacks=None)
    req = LLMRequest(system="s", messages=[Message("user", "q")])
    resp = provider.complete(req)
    assert resp.stop_reason == "refusal" and resp.tool_calls == []
    with pytest.raises(LLMError) as e:
        provider.complete(req)
    assert e.value.kind == "retryable"
    with pytest.raises(LLMError) as e:
        provider.complete(req)
    assert e.value.kind == "fatal"


def test_make_provider_reads_models_yaml(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    cfg = {"roles": {"lead": {"provider": "claude", "model": "claude-opus-5-5"}},
           "providers": {"claude": {"adapter": "anthropic", "fallbacks": None}}}
    provider, role_cfg = make_provider(cfg, "metrics")
    assert isinstance(provider, AnthropicProvider) and role_cfg["model"] == "claude-opus-5-5"
    assert "fallbacks" not in provider.native_request(LLMRequest(system="s", messages=[]))


def test_investigation_runs_through_the_claude_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    client, fake = _client([
        _message([THINKING, {"type": "tool_use", "id": "toolu_1", "name": "get_ci",
                             "input": {"id_or_hostname": "srv-pay-01"}}], "tool_use"),
        _message([{"type": "text", "text": "## Synthèse\nsrv-pay-01 est la CI0012345 [lead/calls/0001.json]"}]),
    ])
    provider = AnthropicProvider(client, "claude-opus-5-5")
    _, status, answer = asyncio.run(cli.ask("Qui est srv-pay-01 ?", providers=only(provider)))

    assert status == "completed" and "CI0012345" in answer
    second = fake.calls[1]["messages"]
    assert second[1]["content"][0] == THINKING
    assert second[2]["content"][0]["tool_use_id"] == "toolu_1"
    assert "CI0012345" in second[2]["content"][0]["content"]


def test_dotenv_is_loaded_without_overriding(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# clés du POC\nANTHROPIC_API_KEY='sk-ant-test'\n"
                                   "export PROMETHEUS_URL=http://192.168.1.15:9090\nDIAGAGENT_DEMO=1\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    monkeypatch.setenv("DIAGAGENT_DEMO", "0")
    cli.load_dotenv(tmp_path / ".env")
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert os.environ["PROMETHEUS_URL"] == "http://192.168.1.15:9090"
    assert os.environ["DIAGAGENT_DEMO"] == "0"
