"""GET JSON minimal (bibliothèque standard), avec délai maximal et jeton facultatif."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TIMEOUT_S = 15


def get_json(base_url: str, path: str, params: dict[str, Any] | None = None,
             bearer_token_env: str | None = None) -> Any:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = os.environ.get(bearer_token_env) if bearer_token_env else None
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise ValueError(f"{base_url} a répondu {e.code} : {body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValueError(f"{base_url} injoignable : {getattr(e, 'reason', e)}") from e
