from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentos.domain.models import Risk


@dataclass(frozen=True)
class Tool:
    name: str
    version: str
    capability: str
    risk: Risk
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], Tool] = {}

    def register(self, tool: Tool) -> None:
        key = (tool.name, tool.version)
        if key in self._tools:
            raise ValueError(f"tool already registered: {tool.name}@{tool.version}")
        self._tools[key] = tool

    def get(self, name: str, version: str = "1") -> Tool:
        try:
            return self._tools[(name, version)]
        except KeyError:
            raise KeyError(f"unknown tool: {name}@{version}") from None

    def manifests(self) -> list[dict[str, str]]:
        return [
            {
                "name": tool.name,
                "version": tool.version,
                "capability": tool.capability,
                "risk": tool.risk.value,
            }
            for tool in self._tools.values()
        ]
