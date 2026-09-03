"""Marketplace registry — reads the local agents/registry.json manifest."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Default manifest path relative to the project root (or install root).
_SEARCH_PATHS = [
    Path(__file__).parent.parent.parent / "agents" / "registry.json",   # dev tree
    Path("/usr/lib/agentos/agents/registry.json"),                       # installed
]


class MarketplaceRegistry:
    """Reads and queries the local agent marketplace manifest."""

    def __init__(self, registry_path: Path | None = None) -> None:
        if registry_path is not None:
            self._path = registry_path
        else:
            self._path = self._find_registry()
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------

    def _find_registry(self) -> Path:
        for p in _SEARCH_PATHS:
            if p.exists():
                return p
        raise FileNotFoundError(
            "agents/registry.json not found. Searched: " + ", ".join(str(p) for p in _SEARCH_PATHS)
        )

    def _load(self) -> dict[str, Any]:
        return json.loads(self._path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------

    def list_agents(self) -> list[dict[str, Any]]:
        """Return all agents in the registry."""
        return list(self._data.get("agents", []))

    def get_agent(self, name: str) -> dict[str, Any] | None:
        """Return the manifest for a named agent, or None if not found."""
        for agent in self._data.get("agents", []):
            if agent.get("name") == name:
                return dict(agent)
        return None
