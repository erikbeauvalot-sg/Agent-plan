"""Déclaration commune des outils : les erreurs attendues reviennent au modèle avec leur message."""

from __future__ import annotations

import functools
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

EXPECTED_ERRORS = (KeyError, ValueError, NotImplementedError)


def read_only_tool(server: MCPServer) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except EXPECTED_ERRORS as e:
                message = e.args[0] if e.args else type(e).__name__
                raise ToolError(str(message)) from e

        server.tool(annotations=ToolAnnotations(read_only_hint=True))(wrapper)
        return fn
    return decorate
