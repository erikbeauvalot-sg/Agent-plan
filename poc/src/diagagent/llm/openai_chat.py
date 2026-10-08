"""Adaptateurs au format Chat Completions : Azure OpenAI et toute API compatible OpenAI.

`azure_openai` vise le déploiement GPT-5.6 Luna du tenant de l'entreprise.
`openai_compatible` vise un serveur local (Ollama, vLLM) ou une passerelle interne.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .base import (
    Capabilities,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    ToolCall,
    Usage,
)

_STOP_REASONS = {
    "stop": "end",
    "tool_calls": "tool_call",
    "function_call": "tool_call",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class OpenAIChatProvider:
    def __init__(self, name: str, client: Any, model: str, supports_reasoning: bool = True,
                 context_tokens: int = 128_000):
        self.name = name
        self._client = client
        self._model = model
        self._supports_reasoning = supports_reasoning
        self._context_tokens = context_tokens

    def capabilities(self) -> Capabilities:
        return Capabilities(context_tokens=self._context_tokens)

    def native_request(self, request: LLMRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        messages += [_to_native_message(m) for m in request.messages]
        params: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": request.max_tokens,
        }
        if request.tools:
            params["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in request.tools
            ]
        if request.reasoning and self._supports_reasoning:
            params["reasoning_effort"] = request.reasoning
        return params

    def complete(self, request: LLMRequest) -> LLMResponse:
        import openai

        try:
            raw = self._client.chat.completions.create(**self.native_request(request))
        except openai.BadRequestError as e:
            if "content_filter" in str(e) or "content management policy" in str(e):
                raise LLMError("refusal", str(e)) from e
            raise LLMError("fatal", str(e)) from e
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError,
                openai.InternalServerError) as e:
            raise LLMError("retryable", str(e)) from e
        except openai.APIError as e:
            raise LLMError("fatal", str(e)) from e

        choice = raw.choices[0]
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=_parse_args(c.function.arguments))
            for c in (choice.message.tool_calls or [])
        ]
        usage = Usage(
            input_tokens=getattr(raw.usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(raw.usage, "completion_tokens", 0) or 0,
        )
        stop = _STOP_REASONS.get(choice.finish_reason or "", "end")
        if calls:
            stop = "tool_call"
        return LLMResponse(
            text=choice.message.content or "",
            tool_calls=calls,
            stop_reason=stop,
            usage=usage,
            model=raw.model or self._model,
            request_id=getattr(raw, "id", None),
            provider_raw=raw.model_dump(mode="json"),
        )


def _to_native_message(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict[str, Any] = {"role": m.role, "content": m.content or None}
    if m.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
            for c in m.tool_calls
        ]
    return out


def _parse_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"_invalid_json": raw}
    return value if isinstance(value, dict) else {"_value": value}


def make_azure_openai(cfg: dict[str, Any], deployment: str) -> OpenAIChatProvider:
    """Client Azure OpenAI. auth: entra_id (DefaultAzureCredential) ou api_key (variable d'env)."""
    from openai import AzureOpenAI

    endpoint = os.path.expandvars(cfg["endpoint"])
    api_version = cfg.get("api_version", "2025-04-01-preview")
    if cfg.get("auth", "entra_id") == "entra_id":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        client = AzureOpenAI(azure_endpoint=endpoint, api_version=api_version,
                             azure_ad_token_provider=token_provider)
    else:
        key = os.environ[cfg.get("api_key_env", "AZURE_OPENAI_API_KEY")]
        client = AzureOpenAI(azure_endpoint=endpoint, api_version=api_version, api_key=key)
    return OpenAIChatProvider("azure_openai", client, deployment,
                              context_tokens=cfg.get("context_tokens", 128_000))


def make_openai_compatible(cfg: dict[str, Any], model: str) -> OpenAIChatProvider:
    from openai import OpenAI

    key = os.environ.get(cfg.get("api_key_env", "OPENAI_COMPATIBLE_API_KEY"), "not-needed")
    client = OpenAI(base_url=os.path.expandvars(cfg["base_url"]), api_key=key)
    return OpenAIChatProvider("openai_compatible", client, model,
                              supports_reasoning=cfg.get("supports_reasoning", False),
                              context_tokens=cfg.get("context_tokens", 32_000))
