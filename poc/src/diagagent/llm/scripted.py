"""Adaptateur sans réseau qui rejoue une suite de réponses : tests et démonstrations hors ligne."""

from __future__ import annotations

from typing import Callable

from .base import Capabilities, LLMRequest, LLMResponse

Step = LLMResponse | Callable[[LLMRequest], LLMResponse]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, steps: list[Step], streams: bool = False):
        self._steps = list(steps)
        self.requests: list[LLMRequest] = []
        self.streams = streams  # diffuse le texte par morceaux de 8 caractères, comme un vrai fournisseur

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def complete(self, request: LLMRequest, on_text: Callable[[str], None] | None = None) -> LLMResponse:
        self.requests.append(request)
        if not self._steps:
            raise RuntimeError("ScriptedProvider : plus de réponse prévue")
        step = self._steps.pop(0)
        response = step(request) if callable(step) else step
        if on_text is not None:
            for i in range(0, len(response.text), 8):
                on_text(response.text[i:i + 8])
        return response
