from types import SimpleNamespace

import pytest

from diagagent.llm import LLMRequest, Message, ToolCall, ToolSpec, select_profile
from diagagent.llm.openai_chat import OpenAIChatProvider


class FakeCompletions:
    def __init__(self):
        self.params = None

    def create(self, **params):
        self.params = params
        call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_ci",
                                                                     arguments='{"id_or_hostname": "srv-pay-01"}'))
        raw = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="tool_calls",
                                     message=SimpleNamespace(content=None, tool_calls=[call]))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=15,
                                  completion_tokens_details=SimpleNamespace(reasoning_tokens=9)), model="gpt-5.6-luna", id="req-1",
            model_dump=lambda mode: {"id": "req-1"})
        return raw


def test_pivot_request_and_response_translation():
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = OpenAIChatProvider("azure_openai", client, "gpt-5.6-luna")
    request = LLMRequest(
        system="sys", reasoning="high",
        messages=[Message("user", "q"),
                  Message("assistant", "", [ToolCall("call_0", "list_sources", {})]),
                  Message("tool", "[]", tool_call_id="call_0")],
        tools=[ToolSpec("get_ci", "Fiche CI", {"type": "object", "properties": {}})])
    resp = provider.complete(request)

    p = completions.params
    assert p["model"] == "gpt-5.6-luna" and p["reasoning_effort"] == "high"
    assert p["messages"][0] == {"role": "system", "content": "sys"}
    assert p["messages"][2]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert p["messages"][3] == {"role": "tool", "tool_call_id": "call_0", "content": "[]"}
    assert p["tools"][0]["function"]["name"] == "get_ci"
    assert resp.stop_reason == "tool_call"
    assert resp.tool_calls[0].arguments == {"id_or_hostname": "srv-pay-01"}
    assert resp.usage.input_tokens == 120
    assert resp.usage.output_tokens == 15 and resp.usage.reasoning_tokens == 9


def test_select_profile():
    local, remote = {"lead": {"provider": "local", "model": "a"}}, {"lead": {"provider": "openai", "model": "b"}}
    cfg = {"default": "ollama", "profiles": {"ollama": local, "openai": remote}, "providers": {}}
    assert select_profile(cfg) == ("ollama", {**cfg, "roles": local})
    assert select_profile(cfg, "openai")[1]["roles"] == remote
    legacy = {"roles": local, "providers": {}}
    assert select_profile(legacy) == ("default", legacy)
    with pytest.raises(ValueError, match="inconnu"):
        select_profile(cfg, "azure")
