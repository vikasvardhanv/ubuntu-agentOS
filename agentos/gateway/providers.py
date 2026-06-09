from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class Provider:
    id: str
    base_url: str
    secret_env: str
    transport: str = "openai_chat"
    local: bool = False
    capabilities: frozenset[str] = frozenset({"chat", "tools"})
    metadata: dict[str, Any] = field(default_factory=dict)


BUILTIN_PROVIDERS: dict[str, Provider] = {
    "openai": Provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": Provider(
        "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "anthropic_messages"
    ),
    "gemini": Provider(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"
    ),
    "grok": Provider("grok", "https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": Provider(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        metadata={"aggregator": True, "data_collection": "configurable"},
    ),
    "ollama": Provider("ollama", "http://127.0.0.1:11434/v1", "", local=True),
    "vllm": Provider("vllm", "http://127.0.0.1:8000/v1", "", local=True),
}

ALIASES = {"xai": "grok", "google": "gemini", "local": "ollama"}


class ProviderRegistry:
    def __init__(self, providers: dict[str, Provider] | None = None):
        self._providers = dict(providers or BUILTIN_PROVIDERS)

    @classmethod
    def from_file(cls, path: Path) -> ProviderRegistry:
        registry = cls()
        if not path.exists():
            return registry
        raw = json.loads(path.read_text(encoding="utf-8"))
        for provider_id, entry in raw.get("providers", {}).items():
            base_url = str(entry["base_url"]).rstrip("/")
            cls._validate_url(base_url, bool(entry.get("local", False)))
            registry._providers[provider_id] = Provider(
                id=provider_id,
                base_url=base_url,
                secret_env=str(entry.get("secret_env", "")),
                transport=str(entry.get("transport", "openai_chat")),
                local=bool(entry.get("local", False)),
                capabilities=frozenset(entry.get("capabilities", ("chat", "tools"))),
                metadata=dict(entry.get("metadata", {})),
            )
        return registry

    def resolve(self, name: str) -> Provider:
        canonical = ALIASES.get(name.strip().lower(), name.strip().lower())
        try:
            return self._providers[canonical]
        except KeyError:
            raise ValueError(f"unknown provider: {name}") from None

    def with_base_url(self, provider: Provider, base_url: str) -> Provider:
        self._validate_url(base_url, provider.local)
        return replace(provider, base_url=base_url.rstrip("/"))

    def list_public(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "transport": item.transport,
                "local": item.local,
                "capabilities": sorted(item.capabilities),
                "configured": not bool(item.secret_env) or bool(os.getenv(item.secret_env)),
            }
            for item in self._providers.values()
        ]

    @staticmethod
    def _validate_url(base_url: str, local: bool) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("provider base_url must be an absolute HTTP(S) URL")
        if not local and parsed.scheme != "https":
            raise ValueError("remote provider base_url must use HTTPS")
