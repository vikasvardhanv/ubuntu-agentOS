from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from agentos.gateway.health import CircuitBreaker
from agentos.gateway.providers import Provider, ProviderRegistry


@dataclass(frozen=True)
class Route:
    provider: Provider
    model: str


@dataclass(frozen=True)
class RoutePolicy:
    providers: tuple[str, ...] = ()
    require: frozenset[str] = frozenset({"chat"})
    local_only: bool = False
    data_collection: str = "deny"


class Router:
    """Hermes-style provider:model resolution with constrained fallbacks."""

    def __init__(
        self,
        fallback_routes: Iterable[str] = (),
        registry: ProviderRegistry | None = None,
        circuits: CircuitBreaker | None = None,
    ):
        self.fallback_routes = tuple(fallback_routes)
        self.registry = registry or ProviderRegistry()
        self.circuits = circuits or CircuitBreaker()

    def candidates(self, requested: str, policy: RoutePolicy) -> list[Route]:
        requested_routes = (requested, *self.fallback_routes)
        routes: list[Route] = []
        seen: set[tuple[str, str]] = set()
        for value in requested_routes:
            route = self._parse(value)
            identity = (route.provider.id, route.model)
            if identity in seen or not self._eligible(route.provider, policy):
                continue
            seen.add(identity)
            routes.append(route)
        if not routes:
            raise ValueError("no provider satisfies routing policy")
        return routes

    def _parse(self, value: str) -> Route:
        if ":" not in value:
            raise ValueError("model route must use provider:model")
        provider_name, model = value.split(":", 1)
        if not provider_name or not model:
            raise ValueError("model route must use provider:model")
        return Route(self.registry.resolve(provider_name), model)

    def _eligible(self, provider: Provider, policy: RoutePolicy) -> bool:
        if policy.providers and provider.id not in policy.providers:
            return False
        if policy.local_only and not provider.local:
            return False
        if not policy.require.issubset(provider.capabilities):
            return False
        if provider.secret_env and not os.getenv(provider.secret_env):
            return False
        if not self.circuits.available(provider.id):
            return False
        return True
