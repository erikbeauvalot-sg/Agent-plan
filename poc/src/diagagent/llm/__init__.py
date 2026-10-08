"""Couche LLM agnostique : interface pivot et adaptateurs par fournisseur."""

from __future__ import annotations

from typing import Any

from .base import (  # noqa: F401
    Capabilities,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)


def make_provider(models_cfg: dict[str, Any], role: str) -> tuple[LLMProvider, dict[str, Any]]:
    """Construit le fournisseur configuré pour un rôle d'agent (config/models.yaml)."""
    role_cfg = models_cfg["roles"][role]
    provider_cfg = models_cfg["providers"][role_cfg["provider"]]
    adapter = provider_cfg["adapter"]
    if adapter == "azure_openai":
        from .openai_chat import make_azure_openai

        return make_azure_openai(provider_cfg, role_cfg["deployment"]), role_cfg
    if adapter == "openai_compatible":
        from .openai_chat import make_openai_compatible

        return make_openai_compatible(provider_cfg, role_cfg["model"]), role_cfg
    raise ValueError(f"Adaptateur LLM inconnu : {adapter}")
