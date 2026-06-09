from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from agentos.gateway.router import Route


class GatewayUpstreamError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Dependency-free adapter for OpenAI-compatible provider endpoints."""

    def complete(self, route: Route, payload: dict[str, Any], timeout: float = 120) -> dict:
        if route.provider.transport != "openai_chat":
            raise GatewayUpstreamError(
                f"{route.provider.id} native transport is registered but not implemented"
            )
        body = dict(payload)
        body["model"] = route.model
        body.pop("route_policy", None)
        request = urllib.request.Request(
            f"{route.provider.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body).encode(),
            headers=self._headers(route),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GatewayUpstreamError(str(error)) from error
        result["agentos_route"] = {
            "provider": route.provider.id,
            "model": route.model,
        }
        return result

    @staticmethod
    def _headers(route: Route) -> dict[str, str]:
        headers = {"content-type": "application/json", "user-agent": "AgentOS/0.1"}
        if route.provider.secret_env:
            headers["authorization"] = f"Bearer {os.environ[route.provider.secret_env]}"
        return headers
