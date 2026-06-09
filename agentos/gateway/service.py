from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor, AuditEvent, Decision, PolicyRequest, Risk
from agentos.gateway.client import GatewayClient
from agentos.gateway.errors import GatewayUpstreamError
from agentos.gateway.router import RoutePolicy, Router
from agentos.policy.engine import PolicyEngine


class Gateway:
    def __init__(
        self,
        router: Router,
        policy: PolicyEngine,
        audit: AuditLog,
        retries: int = 2,
        timeout: float = 120,
    ):
        self.router = router
        self.policy = policy
        self.audit = audit
        self.client = GatewayClient()
        self.retries = max(0, min(retries, 5))
        self.timeout = max(1, min(timeout, 600))

    def complete(self, actor: Actor, payload: dict[str, Any]) -> dict:
        self._validate(payload)
        requested = str(payload["model"])
        request_id = str(uuid4())
        raw_policy = payload.get("route_policy") or {}
        route_policy = RoutePolicy(
            providers=tuple(raw_policy.get("providers", ())),
            require=frozenset(raw_policy.get("require", ("chat",))),
            local_only=bool(raw_policy.get("local_only", False)),
            data_collection=str(raw_policy.get("data_collection", "deny")),
        )
        decision = self.policy.evaluate(PolicyRequest(actor, "llm.infer", requested, Risk.READ))
        self.audit.append(
            AuditEvent(
                "policy.decision",
                actor.id,
                {"capability": "llm.infer", "resource": requested, "result": decision.result},
                correlation_id=request_id,
            )
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)

        errors: list[str] = []
        for route in self.router.candidates(requested, route_policy):
            allow_fallback = True
            for attempt in range(self.retries + 1):
                started = time.monotonic()
                try:
                    response = self.client.complete(route, payload, self.timeout)
                    self.router.circuits.success(route.provider.id)
                    self.audit.append(
                        AuditEvent(
                            "llm.completed",
                            actor.id,
                            {
                                "provider": route.provider.id,
                                "model": route.model,
                                "attempt": attempt + 1,
                                "duration_ms": int((time.monotonic() - started) * 1000),
                                "usage": response.get("usage", {}),
                            },
                            correlation_id=request_id,
                        )
                    )
                    return response
                except GatewayUpstreamError as error:
                    self.router.circuits.failure(route.provider.id)
                    errors.append(f"{route.provider.id}:{error.kind}: {error}")
                    allow_fallback = error.fallback
                    self.audit.append(
                        AuditEvent(
                            "llm.failed",
                            actor.id,
                            {
                                "provider": route.provider.id,
                                "model": route.model,
                                "attempt": attempt + 1,
                                "kind": error.kind,
                                "status": error.status,
                            },
                            correlation_id=request_id,
                        )
                    )
                    if not error.retryable or attempt >= self.retries:
                        break
                    time.sleep(min(0.25 * (2**attempt), 2))
                except ValueError:
                    raise
            if not allow_fallback:
                break
        raise GatewayUpstreamError("; ".join(errors))

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "providers": self.router.registry.list_public(),
            "circuits": self.router.circuits.status(),
        }

    @staticmethod
    def _validate(payload: dict[str, Any]) -> None:
        if not isinstance(payload.get("model"), str) or not payload["model"].strip():
            raise ValueError("model is required")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        if len(messages) > 1000:
            raise ValueError("too many messages")
        if payload.get("stream") not in {None, False}:
            raise ValueError("streaming is not yet supported")
