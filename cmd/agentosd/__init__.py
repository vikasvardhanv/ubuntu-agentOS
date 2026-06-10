from __future__ import annotations

from agentos.api.server import AgentOSServer
from agentos.audit.log import AuditLog
from agentos.config import Settings
from agentos.gateway.providers import ProviderRegistry
from agentos.gateway.router import Router
from agentos.gateway.service import Gateway
from agentos.policy.engine import PolicyEngine
from agentos.runtime.service import AgentRuntime
from agentos.tools.registry import ToolRegistry


def main() -> None:
    settings = Settings.load()
    audit = AuditLog(settings.state_dir / "audit.jsonl")
    policy = PolicyEngine()
    tools = ToolRegistry()
    runtime = AgentRuntime(policy, audit, tools)
    gateway = Gateway(
        Router(
            settings.fallbacks,
            ProviderRegistry.from_file(settings.providers_file, settings.secrets_file),
        ),
        policy,
        audit,
        retries=settings.gateway_retries,
        timeout=settings.gateway_timeout,
    )
    server = AgentOSServer((settings.host, settings.port), runtime, gateway, settings.api_token)
    print(f"agentosd listening on http://{settings.host}:{settings.port}")
    server.serve_forever()
