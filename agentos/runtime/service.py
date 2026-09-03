from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

# Approved grants are only valid for this many seconds after the decision.
APPROVAL_TTL_SECONDS = 300

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
    trust_level: str = "user"
    created_at: str = field(default_factory=utc_now)


@dataclass
class Task:
    agent_id: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    state: str = "pending"   # pending | running | completed | failed
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "state": self.state,
            "payload": self.payload,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ApprovalRequest:
    agent_id: str
    action: str
    resource: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "pending"   # pending | approved | denied
    reason: str = ""
    requested_at: str = field(default_factory=utc_now)
    decided_at: str = ""
    decided_by: str = ""
    expires_at: str = ""
    consumed_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "action": self.action,
            "resource": self.resource,
            "context": self.context,
            "status": self.status,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
        }


class AgentRuntime:
    def __init__(self, policy: PolicyEngine, audit: AuditLog, tools: ToolRegistry):
        self.policy = policy
        self.audit = audit
        self.tools = tools
        self._agents: dict[str, Agent] = {}
        self._tasks: dict[str, Task] = {}              # task_id -> Task
        self._approvals: dict[str, ApprovalRequest] = {}  # approval_id -> ApprovalRequest
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ agents

    def register(self, actor: Actor, name: str, capabilities: list[str],
                 trust_level: str = "user") -> dict[str, Any]:
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.register", name, Risk.MODIFY)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        agent = Agent(name=name, capabilities=tuple(capabilities), trust_level=trust_level)
        with self._lock:
            self._agents[agent.id] = agent
        self.audit.append(AuditEvent("agent.registered", actor.id, asdict(agent)))
        return asdict(agent)

    def get_agent(self, actor: Actor, agent_id: str) -> dict[str, Any]:
        decision = self.policy.evaluate(PolicyRequest(actor, "agent.read", agent_id, Risk.READ))
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"agent not found: {agent_id}")
        return asdict(agent)

    def unregister(self, actor: Actor, agent_id: str) -> dict[str, Any]:
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.unregister", agent_id, Risk.MODIFY)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            agent = self._agents.pop(agent_id, None)
        if agent is None:
            raise KeyError(f"agent not found: {agent_id}")
        self.audit.append(AuditEvent("agent.unregistered", actor.id, {"agent_id": agent_id}))
        return {"id": agent_id, "state": "unregistered"}

    def list_agents(self, actor: Actor) -> list[dict[str, Any]]:
        decision = self.policy.evaluate(PolicyRequest(actor, "agent.task.submit", "*", Risk.MODIFY))
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            return [asdict(agent) for agent in self._agents.values()]

    # ------------------------------------------------------------------ tasks

    def submit_task(self, actor: Actor, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit a task to a registered agent. Runs synchronously in this milestone."""
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.task.submit", agent_id, Risk.MODIFY)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"agent not found: {agent_id}")
        task = Task(agent_id=agent_id, payload=payload)
        with self._lock:
            self._tasks[task.id] = task
        self.audit.append(
            AuditEvent("task.submitted", actor.id, {"task_id": task.id, "agent_id": agent_id})
        )
        # Execute inline — future milestones will dispatch to a worker pool.
        self._execute(task, actor)
        return task.as_dict()

    def get_task(self, actor: Actor, agent_id: str, task_id: str) -> dict[str, Any]:
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.task.read", agent_id, Risk.READ)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None or task.agent_id != agent_id:
            raise KeyError(f"task not found: {task_id}")
        return task.as_dict()

    def update_task(self, actor: Actor, agent_id: str, task_id: str, state: str,
                    result: dict[str, Any] | None = None, error: str = "") -> dict[str, Any]:
        """Update a task's execution state (used by agents reporting results).

        Only tasks that are still pending/running may be updated; terminal
        states are immutable.
        """
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.task.update", agent_id, Risk.MODIFY)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        if state not in {"running", "completed", "failed"}:
            raise ValueError(f"invalid task state: {state!r}")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.agent_id != agent_id:
                raise KeyError(f"task not found: {task_id}")
            if task.state not in {"pending", "running"}:
                raise ValueError(f"task {task_id} is already {task.state}")
            task.state = state
            if result is not None:
                task.result = result
            if error:
                task.error = error
            task.updated_at = utc_now()
        self.audit.append(
            AuditEvent("task.updated", actor.id,
                       {"task_id": task_id, "agent_id": agent_id, "state": state})
        )
        return task.as_dict()

    def list_tasks(self, actor: Actor, agent_id: str) -> list[dict[str, Any]]:
        decision = self.policy.evaluate(
            PolicyRequest(actor, "agent.task.read", agent_id, Risk.READ)
        )
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            return [t.as_dict() for t in self._tasks.values() if t.agent_id == agent_id]

    # ------------------------------------------------------------------ approvals

    def request_approval(self, actor: Actor, agent_id: str, action: str,
                         resource: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a pending human-approval request."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"agent not found: {agent_id}")
        approval = ApprovalRequest(
            agent_id=agent_id,
            action=action,
            resource=resource,
            context=context or {},
        )
        with self._lock:
            self._approvals[approval.id] = approval
        self.audit.append(
            AuditEvent("approval.requested", actor.id,
                       {"approval_id": approval.id, "agent_id": agent_id, "action": action})
        )
        return approval.as_dict()

    def list_pending_approvals(self, actor: Actor) -> list[dict[str, Any]]:
        decision = self.policy.evaluate(PolicyRequest(actor, "agent.task.submit", "*", Risk.MODIFY))
        if decision.result is not Decision.ALLOW:
            raise PermissionError(decision.reason)
        with self._lock:
            return [a.as_dict() for a in self._approvals.values() if a.status == "pending"]

    def decide_approval(self, actor: Actor, approval_id: str,
                        approved: bool, reason: str = "") -> dict[str, Any]:
        """Approve or deny a pending approval request."""
        with self._lock:
            approval = self._approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"approval not found: {approval_id}")
        if approval.status != "pending":
            raise ValueError(f"approval {approval_id} is already {approval.status}")
        approval.status = "approved" if approved else "denied"
        approval.reason = reason
        approval.decided_at = utc_now()
        approval.decided_by = actor.id
        if approved:
            expiry = datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_TTL_SECONDS)
            approval.expires_at = expiry.isoformat()
        self.audit.append(
            AuditEvent(
                "approval.decided", actor.id,
                {"approval_id": approval_id, "status": approval.status, "reason": reason}
            )
        )
        return approval.as_dict()

    def validate_approval(self, token: str, action: str, agent_id: str) -> bool:
        """Validate an approval token presented by a privileged caller.

        The token must be the id of an approval that was granted, matches the
        requested action and agent, has not expired (APPROVAL_TTL_SECONDS),
        and has not already been consumed. Valid tokens are single-use:
        successful validation consumes them.
        """
        if not token:
            return False
        with self._lock:
            approval = self._approvals.get(token)
            if approval is None or approval.status != "approved":
                return False
            if approval.consumed_at:
                return False
            if approval.action != action or approval.agent_id != agent_id:
                return False
            try:
                expires = datetime.fromisoformat(approval.expires_at)
            except ValueError:
                return False
            if datetime.now(timezone.utc) > expires:
                return False
            approval.consumed_at = utc_now()
        self.audit.append(
            AuditEvent("approval.consumed", agent_id,
                       {"approval_id": token, "action": action})
        )
        return True

    # ------------------------------------------------------------------ internal

    def _execute(self, task: Task, actor: Actor) -> None:
        """Execute a task payload. Dispatches to registered tool handlers."""
        task.state = "running"
        task.updated_at = utc_now()
        try:
            capability = str(task.payload.get("capability", ""))
            arguments = dict(task.payload.get("arguments", {}))
            if not capability:
                raise ValueError("task payload must include 'capability'")
            # Look up a registered tool handler; fall back to an acknowledged echo so
            # callers can track task lifecycle without crashing the runtime.
            try:
                tool = self.tools.get(capability)
                result = tool.handler(arguments)
            except KeyError:
                result = {"acknowledged": True, "capability": capability, "arguments": arguments}
            task.state = "completed"
            task.result = result
        except Exception as exc:
            task.state = "failed"
            task.error = str(exc)
        finally:
            task.updated_at = utc_now()
        self.audit.append(
            AuditEvent(
                "task.completed" if task.state == "completed" else "task.failed",
                actor.id,
                {"task_id": task.id, "agent_id": task.agent_id, "state": task.state},
            )
        )
