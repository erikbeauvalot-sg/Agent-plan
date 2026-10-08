"""Adaptateur sans réseau qui rejoue une suite de réponses : tests et démonstrations hors ligne."""

from __future__ import annotations

from typing import Callable

from .base import Capabilities, LLMRequest, LLMResponse

Step = LLMResponse | Callable[[LLMRequest], LLMResponse]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, steps: list[Step]):
        self._steps = list(steps)
        self.requests: list[LLMRequest] = []

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._steps:
            raise RuntimeError("ScriptedProvider : plus de réponse prévue")
        step = self._steps.pop(0)
        return step(request) if callable(step) else step
