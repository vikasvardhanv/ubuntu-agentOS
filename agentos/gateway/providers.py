from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Provider:
    id: str
    base_url: str
    secret_env: str
    transport: str = "openai_chat"
    local: bool = False
    capabilities: frozenset[str] = frozenset({"chat", "tools"})
    metadata: dict[str, Any] = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    "openai": Provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": Provider(
        "anthropic",
        "https://api.anthropic.com",
        "ANTHROPIC_API_KEY",
        transport="anthropic_messages",
    ),
    "gemini": Provider(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
    "grok": Provider("grok", "https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": Provider(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        metadata={"aggregator": True},
    ),
    "ollama": Provider("ollama", "http://127.0.0.1:11434/v1", "", local=True),
    "vllm": Provider("vllm", "http://127.0.0.1:8000/v1", "", local=True),
}

ALIASES = {"xai": "grok", "google": "gemini", "local": "ollama"}


def resolve_provider(name: str) -> Provider:
    canonical = ALIASES.get(name.strip().lower(), name.strip().lower())
    try:
        return PROVIDERS[canonical]
    except KeyError:
        raise ValueError(f"unknown provider: {name}") from None
