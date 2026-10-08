"""Format pivot de la couche LLM : la logique d'agent ne connaît que ces types."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Protocol

StopReason = Literal["end", "tool_call", "max_tokens", "refusal", "error"]
Reasoning = Literal["low", "medium", "high"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    # Contenu natif d'un tour assistant, renvoyé tel quel par l'adaptateur qui l'a produit
    # (Claude exige de recevoir ses blocs de réflexion inchangés). Ignoré par les autres adaptateurs.
    native: Any = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    max_tokens: int = 4000
    reasoning: Reasoning | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    request_id: str | None = None
    provider_raw: Any = None
    native: Any = None


@dataclass
class Capabilities:
    tool_calls: bool = True
    parallel_tool_calls: bool = True
    structured_output: bool = False
    context_tokens: int = 128_000


class LLMError(Exception):
    """Erreur normalisée : kind vaut retryable, fatal ou refusal."""

    def __init__(self, kind: Literal["retryable", "fatal", "refusal"], message: str):
        super().__init__(message)
        self.kind = kind


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def capabilities(self) -> Capabilities: ...


def to_jsonable(obj: Any) -> Any:
    """Sérialise les dataclasses du format pivot pour les transcripts."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj
