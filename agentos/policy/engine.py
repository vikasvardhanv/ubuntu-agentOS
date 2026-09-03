from __future__ import annotations

from typing import Any

from agentos.domain.models import Decision, PolicyDecision, PolicyRequest, Risk


# ---------------------------------------------------------------------------
# RBAC role grants: maps role name -> set of capability patterns.
# "*" is a wildcard for all capabilities.
# "prefix.*" matches any capability starting with "prefix.".
# ---------------------------------------------------------------------------
DEFAULT_GRANTS: dict[str, set[str]] = {
    "administrator": {"*"},
    "operator": {
        "agent.*",
        "llm.infer",
        "tool.read",
        "tool.modify",
    },
    "viewer": {"agent.read", "tool.read"},
    "readonly": {"agent.read", "tool.read"},
}

# ---------------------------------------------------------------------------
# ABAC attribute rules
#
# Each rule is a dict with:
#   "match_capability": glob pattern (same syntax as RBAC grants)
#   "match_risk": optional Risk value that must match
#   "require_attributes": dict of {attribute_path: expected_value}
#       Attribute paths are dot-separated keys into PolicyRequest.context.
#       If ALL required attributes match, the rule applies.
#   "effect": "deny" | "require_approval"
#   "reason": human-readable explanation
#
# Rules are evaluated AFTER RBAC grants succeed and BEFORE the risk gate.
# A matching "deny" rule hard-denies regardless of risk.
# A matching "require_approval" rule triggers the human-approval gate.
# ---------------------------------------------------------------------------
DEFAULT_ABAC_RULES: list[dict[str, Any]] = [
    # Untrusted agents (trust_level == "untrusted") may never call external
    # capabilities regardless of the actor's role.
    {
        "match_capability": "llm.infer",
        "require_attributes": {"agent.trust_level": "untrusted"},
        "effect": "deny",
        "reason": "untrusted agent may not invoke external inference",
    },
    {
        "match_capability": "tool.*",
        "require_attributes": {"agent.trust_level": "untrusted"},
        "effect": "deny",
        "reason": "untrusted agent may not use tools",
    },
    # High-sensitivity resources always require human approval, even for operators.
    {
        "match_capability": "*",
        "require_attributes": {"resource.sensitivity": "high"},
        "effect": "require_approval",
        "reason": "high-sensitivity resource requires human approval",
    },
    # Sandboxed agents must stay local (no external LLM calls).
    {
        "match_capability": "llm.infer",
        "require_attributes": {"agent.trust_level": "sandboxed"},
        "match_risk": Risk.EXTERNAL,
        "effect": "require_approval",
        "reason": "sandboxed agent requires approval for external inference",
    },
]


class PolicyEngine:
    """Policy engine with RBAC grants and ABAC attribute rules.

    Evaluation order (fail-closed at every step):
    1. PROHIBITED risk  → always DENY
    2. RBAC check       → DENY if no matching role grant
    3. ABAC rules       → DENY or REQUIRE_APPROVAL if a rule matches
    4. Risk gate        → REQUIRE_APPROVAL for EXTERNAL/PRIVILEGED without prior approval
    5. Default          → ALLOW
    """

    def __init__(
        self,
        grants: dict[str, set[str]] | None = None,
        abac_rules: list[dict[str, Any]] | None = None,
    ):
        self.grants = grants if grants is not None else dict(DEFAULT_GRANTS)
        self.abac_rules = abac_rules if abac_rules is not None else list(DEFAULT_ABAC_RULES)

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        # Step 1 – prohibited capability is always denied.
        if request.risk is Risk.PROHIBITED:
            return PolicyDecision(Decision.DENY, "prohibited capability")

        # Step 2 – RBAC: at least one role must grant the capability.
        granted = any(
            self._matches(capability, request.capability)
            for role in request.actor.roles
            for capability in self.grants.get(role, set())
        )
        if not granted:
            return PolicyDecision(Decision.DENY, "no matching role grant")

        # Step 3 – ABAC attribute rules.
        abac_result = self._evaluate_abac(request)
        if abac_result is not None:
            return abac_result

        # Step 4 – Risk gate: EXTERNAL and PRIVILEGED require a fresh approval token.
        if request.risk in {Risk.EXTERNAL, Risk.PRIVILEGED}:
            approval = request.context.get("approval")
            if not approval:
                return PolicyDecision(
                    Decision.REQUIRE_APPROVAL,
                    "fresh approval required for consequential action",
                    {"approval_scope": request.capability, "resource": request.resource},
                )

        return PolicyDecision(Decision.ALLOW, "role and risk policy satisfied")

    def _evaluate_abac(self, request: PolicyRequest) -> PolicyDecision | None:
        """Return a PolicyDecision if any ABAC rule fires, else None."""
        for rule in self.abac_rules:
            if not self._matches(rule.get("match_capability", "*"), request.capability):
                continue
            match_risk = rule.get("match_risk")
            if match_risk is not None and request.risk is not match_risk:
                continue
            require_attrs: dict[str, Any] = rule.get("require_attributes", {})
            if not self._attributes_match(require_attrs, request.context):
                continue
            effect = rule.get("effect", "deny")
            reason = str(rule.get("reason", "denied by ABAC rule"))
            if effect == "deny":
                return PolicyDecision(Decision.DENY, reason)
            if effect == "require_approval":
                approval = request.context.get("approval")
                if not approval:
                    return PolicyDecision(
                        Decision.REQUIRE_APPROVAL,
                        reason,
                        {"approval_scope": request.capability, "resource": request.resource},
                    )
        return None

    @staticmethod
    def _attributes_match(required: dict[str, Any], context: dict[str, Any]) -> bool:
        """Check all required attribute paths against the request context."""
        for dotted_path, expected in required.items():
            node: Any = context
            for key in dotted_path.split("."):
                if not isinstance(node, dict):
                    return False
                node = node.get(key)
            if node != expected:
                return False
        return True

    @staticmethod
    def _matches(grant: str, capability: str) -> bool:
        return grant == "*" or grant == capability or (
            grant.endswith(".*") and capability.startswith(grant[:-1])
        )
