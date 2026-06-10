from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from agentos.gateway.errors import GatewayUpstreamError, classify
from agentos.gateway.providers import Provider


def discover_models(provider: Provider, secret: str = "", timeout: float = 20) -> list[str]:
    """Discover model IDs from a configured provider without assuming a default."""
    headers = {"accept": "application/json", "user-agent": "AgentOS-Onboarding/0.2"}
    if secret:
        if provider.transport == "anthropic_messages":
            headers |= {"x-api-key": secret, "anthropic-version": "2023-06-01"}
        else:
            headers["authorization"] = f"Bearer {secret}"
    request = urllib.request.Request(f"{provider.base_url.rstrip('/')}/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body: dict[str, Any] = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise classify(error.code, error.read().decode(errors="replace")[:4096]) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GatewayUpstreamError(f"model discovery failed: {error}") from error

    models = body.get("data") or body.get("models") or []
    result: list[str] = []
    for item in models:
        model_id = item.get("id") or item.get("name") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id.strip():
            result.append(model_id.removeprefix("models/"))
    return sorted(set(result))
