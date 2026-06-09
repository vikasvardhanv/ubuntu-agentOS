from __future__ import annotations

import os
from pathlib import Path

from agentos.api.server import AgentOSServer
from agentos.audit.log import AuditLog
from agentos.gateway.router import Router
from agentos.gateway.service import Gateway
from agentos.policy.engine import PolicyEngine
from agentos.runtime.service import AgentRuntime
from agentos.tools.registry import ToolRegistry


def main() -> None:
    state_dir = Path(os.getenv("AGENTOS_STATE_DIR", "./var"))
    audit = AuditLog(state_dir / "audit.jsonl")
    policy = PolicyEngine()
    tools = ToolRegistry()
    runtime = AgentRuntime(policy, audit, tools)
    fallbacks = tuple(
        value.strip()
        for value in os.getenv("AGENTOS_GATEWAY_FALLBACKS", "").split(",")
        if value.strip()
    )
    gateway = Gateway(Router(fallbacks), policy, audit)
    host = os.getenv("AGENTOS_LISTEN_HOST", "127.0.0.1")
    port = int(os.getenv("AGENTOS_LISTEN_PORT", "7788"))
    server = AgentOSServer((host, port), runtime, gateway)
    print(f"agentosd listening on http://{host}:{port}")
    server.serve_forever()
