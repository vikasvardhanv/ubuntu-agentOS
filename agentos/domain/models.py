from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class Risk(StrEnum):
    READ = "read"
    MODIFY = "modify"
    EXTERNAL = "external"
    PRIVILEGED = "privileged"
    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class Actor:
    id: str
    tenant_id: str = "local"
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyRequest:
    actor: Actor
    capability: str
    resource: str
    risk: Risk
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    result: Decision
    reason: str
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEvent:
    event_type: str
    actor_id: str
    data: dict[str, Any]
    tenant_id: str = "local"
    correlation_id: str = ""
    causation_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
