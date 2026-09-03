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
    secret: str = field(default="", repr=False, compare=False)


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
    "lmstudio": Provider("lmstudio", "http://127.0.0.1:1234/v1", "", local=True),
    "deepseek": Provider("deepseek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "mistral": Provider("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "groq": Provider("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "together": Provider(
        "together",
        "https://api.together.xyz/v1",
        "TOGETHER_API_KEY",
        metadata={"aggregator": True},
    ),
    "fireworks": Provider("fireworks", "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "cerebras": Provider("cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "moonshot": Provider("moonshot", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    "zai": Provider("zai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
    "minimax": Provider(
        "minimax", "https://api.minimax.io/anthropic", "MINIMAX_API_KEY", "anthropic_messages"
    ),
    "dashscope": Provider("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "nous": Provider("nous", "https://inference-api.nousresearch.com/v1", "NOUS_API_KEY"),
}

ALIASES = {
    "xai": "grok",
    "google": "gemini",
    "local": "ollama",
    "qwen": "dashscope",
    "alibaba": "dashscope",
    "kimi": "moonshot",
    "glm": "zai",
}


class ProviderRegistry:
    def __init__(
        self,
        providers: dict[str, Provider] | None = None,
        selected_route: str = "",
        configured_ids: set[str] | None = None,
    ):
        self._providers = dict(providers or BUILTIN_PROVIDERS)
        self.selected_route = selected_route
        self.configured_ids = configured_ids or set()

    @classmethod
    def from_file(cls, path: Path, secrets_path: Path | None = None) -> ProviderRegistry:
        registry = cls()
        if not path.exists():
            return registry
        raw = json.loads(path.read_text(encoding="utf-8"))
        secrets = {}
        if secrets_path and secrets_path.exists():
            secrets = json.loads(secrets_path.read_text(encoding="utf-8")).get("providers", {})
        registry.selected_route = str(raw.get("selected_route", "")).strip()
        for provider_id, entry in raw.get("providers", {}).items():
            builtin = BUILTIN_PROVIDERS.get(provider_id)
            base_url = str(entry.get("base_url") or (builtin.base_url if builtin else "")).rstrip("/")
            cls._validate_url(base_url, bool(entry.get("local", False)))
            registry._providers[provider_id] = Provider(
                id=provider_id,
                base_url=base_url,
                secret_env=str(entry.get("secret_env") or (builtin.secret_env if builtin else "")),
                transport=str(entry.get("transport") or (builtin.transport if builtin else "openai_chat")),
                local=bool(entry.get("local", builtin.local if builtin else False)),
                capabilities=frozenset(
                    entry.get("capabilities", builtin.capabilities if builtin else ("chat", "tools"))
                ),
                metadata=dict(entry.get("metadata", {})),
                secret=str(secrets.get(provider_id, "")),
            )
            registry.configured_ids.add(provider_id)
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
                "configured": item.id in self.configured_ids or bool(os.getenv(item.secret_env)),
                "selected": self.selected_route.startswith(f"{item.id}:"),
            }
            for item in self._providers.values()
        ]

    def credential(self, provider: Provider) -> str:
        return provider.secret or (os.getenv(provider.secret_env, "") if provider.secret_env else "")

    @staticmethod
    def _validate_url(base_url: str, local: bool) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("provider base_url must be an absolute HTTP(S) URL")
        if not local and parsed.scheme != "https":
            raise ValueError("remote provider base_url must use HTTPS")
