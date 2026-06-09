from __future__ import annotations

from typing import Any

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor, AuditEvent, Decision, PolicyRequest, Risk
from agentos.gateway.client import GatewayUpstreamError, OpenAICompatibleClient
from agentos.gateway.router import RoutePolicy, Router
from agentos.policy.engine import PolicyEngine


class Gateway:
    def __init__(self, router: Router, policy: PolicyEngine, audit: AuditLog):
        self.router = router
        self.policy = policy
        self.audit = audit
        self.client = OpenAICompatibleClient()

    def complete(self, actor: Actor, payload: dict[str, Any]) -> dict:
        requested = str(payload.get("model", ""))
        raw_policy = payload.get("route_policy") or {}
        route_policy = RoutePolicy(
            providers=tuple(raw_policy.get("providers", ())),
            require=frozenset(raw_policy.get("require", ("chat",))),
            local_only=bool(raw_policy.get("local_only", False)),
            data_collection=str(raw_policy.get("data_collection", "deny")),
        )
        decision = self.policy.evaluate(
            PolicyRequest(actor, "llm.infer", requested, Risk.READ)
        )
        self.audit.append(
            AuditEvent(
                "policy.decision",
                actor.id,
                {"capability": "llm.infer", "resource": requested, "result": decision.result},
            )
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)

        errors: list[str] = []
        for route in self.router.candidates(requested, route_policy):
            try:
                response = self.client.complete(route, payload)
                self.audit.append(
                    AuditEvent(
                        "llm.completed",
                        actor.id,
                        {"provider": route.provider.id, "model": route.model},
                    )
                )
                return response
            except GatewayUpstreamError as error:
                errors.append(f"{route.provider.id}: {error}")
        raise GatewayUpstreamError("; ".join(errors))
