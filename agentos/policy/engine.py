from __future__ import annotations

from agentos.domain.models import Decision, PolicyDecision, PolicyRequest, Risk


class PolicyEngine:
    """Small reference policy engine with production fail-closed semantics."""

    def __init__(self, grants: dict[str, set[str]] | None = None):
        self.grants = grants or {
            "administrator": {"*"},
            "operator": {"agent.*", "llm.infer", "tool.read", "tool.modify"},
            "viewer": {"agent.read", "tool.read"},
        }

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        if request.risk is Risk.PROHIBITED:
            return PolicyDecision(Decision.DENY, "prohibited capability")

        granted = any(
            self._matches(capability, request.capability)
            for role in request.actor.roles
            for capability in self.grants.get(role, set())
        )
        if not granted:
            return PolicyDecision(Decision.DENY, "no matching role grant")

        if request.risk in {Risk.EXTERNAL, Risk.PRIVILEGED}:
            approval = request.context.get("approval")
            if not approval:
                return PolicyDecision(
                    Decision.REQUIRE_APPROVAL,
                    "fresh approval required for consequential action",
                    {"approval_scope": request.capability, "resource": request.resource},
                )
        return PolicyDecision(Decision.ALLOW, "role and risk policy satisfied")

    @staticmethod
    def _matches(grant: str, capability: str) -> bool:
        return grant == "*" or grant == capability or (
            grant.endswith(".*") and capability.startswith(grant[:-1])
        )
