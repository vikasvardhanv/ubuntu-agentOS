from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor, AuditEvent, Decision, PolicyRequest, Risk, utc_now
from agentos.policy.engine import PolicyEngine
from agentos.tools.registry import ToolRegistry


@dataclass
class Agent:
    name: str
    capabilities: tuple[str, ...]
    id: str = field(default_factory=lambda: str(uuid4()))
    state: str = "registered"
    created_at: str = field(default_factory=utc_now)


class AgentRuntime:
    def __init__(self, policy: PolicyEngine, audit: AuditLog, tools: ToolRegistry):
        self.policy = policy
        self.audit = audit
        self.tools = tools
        self._agents: dict[str, Agent] = {}
        self._lock = threading.Lock()

    def register(self, actor: Actor, name: str, capabilities: list[str]) -> dict[str, Any]:
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.register", name, Risk.MODIFY)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        agent = Agent(name=name, capabilities=tuple(capabilities))
        with self._lock:
            self._agents[agent.id] = agent
        self.audit.append(AuditEvent("agent.registered", actor.id, asdict(agent)))
        return asdict(agent)

    def list_agents(self, actor: Actor) -> list[dict[str, Any]]:
        decision = self.policy.evaluate(PolicyRequest(actor, "agent.read", "*", Risk.READ))
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            return [asdict(agent) for agent in self._agents.values()]
