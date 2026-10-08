"""Adaptateur `anthropic` : l'API Messages de Claude, pour le POC à la maison.

En production le modèle reste hébergé dans le tenant de l'entreprise (adaptateur `azure_openai`) :
les données de production ne partent pas chez un fournisseur externe. Cet adaptateur sert au POC,
dont les sources sont celles d'Erik.

Points propres à Claude :
- la réflexion adaptative est toujours active sur Claude Opus 5.5 ; `reasoning` règle l'effort ;
- les blocs de réflexion d'un tour doivent revenir inchangés au tour suivant : ils voyagent dans
  `LLMResponse.native` puis `Message.native` ;
- les résultats d'outils d'un même tour partent ensemble dans un seul message utilisateur ;
- `fallbacks: default` laisse l'API relancer une requête refusée par un filtre de sûreté sur le
  modèle de repli recommandé, au lieu de renvoyer un refus.
"""

from __future__ import annotations

import os
from typing import Any

from .base import Capabilities, LLMError, LLMRequest, LLMResponse, Message, ToolCall, Usage

_STOP_REASONS = {
    "end_turn": "end",
    "stop_sequence": "end",
    "pause_turn": "end",
    "tool_use": "tool_call",
    "max_tokens": "max_tokens",
    "model_context_window_exceeded": "max_tokens",
    "refusal": "refusal",
}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: Any, model: str, *, max_tokens: int = 16_000, fallbacks: str | None = "default",
                 cache: bool = True, context_tokens: int = 1_000_000):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._fallbacks = fallbacks
        self._cache = cache
        self._context_tokens = context_tokens

    def capabilities(self) -> Capabilities:
        return Capabilities(context_tokens=self._context_tokens)

    def native_request(self, request: LLMRequest) -> dict[str, Any]:
        # max_tokens couvre aussi la réflexion : on ne descend pas sous le plancher configuré.
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max(request.max_tokens, self._max_tokens),
            "system": request.system,
            "messages": to_native_messages(request.messages),
            "thinking": {"type": "adaptive"},
        }
        if request.tools:
            params["tools"] = [{"name": t.name, "description": t.description,
                                "input_schema": t.parameters or {"type": "object", "properties": {}}}
                               for t in request.tools]
        if request.reasoning:
            params["output_config"] = {"effort": request.reasoning}
        if self._cache:
            # L'historique grossit à chaque tour : le préfixe déjà envoyé est relu depuis le cache.
            params["cache_control"] = {"type": "ephemeral"}
        if self._fallbacks:
            params["fallbacks"] = self._fallbacks
            params["betas"] = [_FALLBACK_BETA]
        return params

    def complete(self, request: LLMRequest) -> LLMResponse:
        import anthropic

        params = self.native_request(request)
        api = self._client.beta.messages if "betas" in params else self._client.messages
        try:
            raw = api.create(**params)
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            raise LLMError("retryable", str(e)) from e
        except anthropic.APIStatusError as e:
            kind = "retryable" if e.status_code in (408, 409, 429) or e.status_code >= 500 else "fatal"
            raise LLMError(kind, str(e)) from e
        except anthropic.APIError as e:
            raise LLMError("fatal", str(e)) from e

        blocks = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in raw.content]
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in blocks if b["type"] == "tool_use"]
        text = "\n\n".join(b["text"] for b in blocks if b["type"] == "text")
        stop = _STOP_REASONS.get(raw.stop_reason or "", "end")
        if stop == "refusal":
            # Le refus (y compris après repli) n'est pas exploitable : on n'exécute aucun outil.
            calls = []
        elif calls:
            stop = "tool_call"
        usage = raw.usage
        return LLMResponse(
            text=text,
            tool_calls=calls,
            stop_reason=stop,  # type: ignore[arg-type]
            usage=Usage(
                input_tokens=(usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
                output_tokens=usage.output_tokens or 0,
            ),
            model=raw.model or self._model,
            request_id=getattr(raw, "_request_id", None) or raw.id,
            provider_raw=raw.model_dump(mode="json", by_alias=True, exclude_none=True),
            native=blocks,
        )


def to_native_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Format pivot → messages Claude. Les tours consécutifs du même rôle sont fusionnés : les
    résultats d'outils d'un tour et une éventuelle consigne qui les suit forment un seul message."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = "assistant" if m.role == "assistant" else "user"
        if m.role == "tool":
            blocks = [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or "(vide)"}]
        elif m.role == "assistant" and m.native is not None:
            blocks = list(m.native)
        elif m.role == "assistant":
            blocks = ([{"type": "text", "text": m.content}] if m.content else []) + [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
        else:
            blocks = [{"type": "text", "text": m.content}]
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    return out


def make_anthropic(cfg: dict[str, Any], model: str) -> AnthropicProvider:
    """Client Claude. Sans `api_key_env`, le SDK lit ANTHROPIC_API_KEY (ou un profil `ant auth login`)."""
    import anthropic

    kwargs: dict[str, Any] = {}
    if cfg.get("api_key_env"):
        kwargs["api_key"] = os.environ[cfg["api_key_env"]]
    if cfg.get("base_url"):
        kwargs["base_url"] = os.path.expandvars(cfg["base_url"])
    client = anthropic.Anthropic(**kwargs)
    return AnthropicProvider(client, model, max_tokens=cfg.get("max_tokens", 16_000),
                             fallbacks=cfg.get("fallbacks", "default"), cache=cfg.get("cache", True),
                             context_tokens=cfg.get("context_tokens", 1_000_000))
