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


def _chunk(content=None, tool=None, finish=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=[tool] if tool else None)
    return SimpleNamespace(id="req-2", model="gpt-4.1-mini-2025-04-14", usage=usage,
                           choices=[SimpleNamespace(delta=delta, finish_reason=finish)] if usage is None else [])


class StreamingCompletions:
    def __init__(self, chunks, refuse=False):
        self.chunks, self.refuse, self.calls = chunks, refuse, []

    def create(self, **params):
        import httpx
        import openai

        self.calls.append(params)
        if params.get("stream") and self.refuse:
            raise openai.BadRequestError("stream not supported", response=httpx.Response(
                400, request=httpx.Request("POST", "http://x")), body=None)
        return iter(self.chunks) if params.get("stream") else FakeCompletions().create(**params)


def test_streamed_text_reaches_the_callback_and_tool_calls_are_rebuilt():
    tool = lambda i, name, args, id_=None: SimpleNamespace(  # noqa: E731
        index=i, id=id_, function=SimpleNamespace(name=name, arguments=args))
    chunks = [_chunk("## Synth"), _chunk("èse\nok"),
              _chunk(tool=tool(0, "get_ci", '{"id_or', "call_9")), _chunk(tool=tool(0, "", '_hostname": "a"}')),
              _chunk(finish="tool_calls"),
              _chunk(usage=SimpleNamespace(prompt_tokens=50, completion_tokens=7, completion_tokens_details=None))]
    completions = StreamingCompletions(chunks)
    provider = OpenAIChatProvider("openai", SimpleNamespace(chat=SimpleNamespace(completions=completions)), "gpt-4.1-mini")
    seen = []
    resp = provider.complete(LLMRequest(system="s", messages=[Message("user", "q")]), on_text=seen.append)
    assert seen == ["## Synth", "èse\nok"] and resp.text == "## Synthèse\nok"
    assert resp.tool_calls == [ToolCall("call_9", "get_ci", {"id_or_hostname": "a"})]
    assert resp.stop_reason == "tool_call" and resp.usage.input_tokens == 50
    assert completions.calls[0]["stream_options"] == {"include_usage": True}


def test_server_without_streaming_falls_back_to_a_plain_call():
    completions = StreamingCompletions([], refuse=True)
    provider = OpenAIChatProvider("openai", SimpleNamespace(chat=SimpleNamespace(completions=completions)), "m")
    resp = provider.complete(LLMRequest(system="s", messages=[Message("user", "q")]), on_text=lambda t: None)
    assert resp.tool_calls[0].name == "get_ci" and provider.streams is False
    assert [bool(c.get("stream")) for c in completions.calls] == [True, False]


def test_select_profile():
    local, remote = {"lead": {"provider": "local", "model": "a"}}, {"lead": {"provider": "openai", "model": "b"}}
    cfg = {"default": "ollama", "profiles": {"ollama": local, "openai": remote}, "providers": {}}
    assert select_profile(cfg) == ("ollama", {**cfg, "roles": local})
    assert select_profile(cfg, "openai")[1]["roles"] == remote
    legacy = {"roles": local, "providers": {}}
    assert select_profile(legacy) == ("default", legacy)
    with pytest.raises(ValueError, match="inconnu"):
        select_profile(cfg, "azure")
