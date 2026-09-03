from __future__ import annotations

import logging
import sys

from agentos.api.server import AgentOSServer
from agentos.audit.log import AuditLog
from agentos.config import Settings
from agentos.gateway.providers import ProviderRegistry
from agentos.gateway.router import Router
from agentos.gateway.service import Gateway
from agentos.policy.engine import PolicyEngine
from agentos.runtime.service import AgentRuntime
from agentos.tools.registry import ToolRegistry

log = logging.getLogger("agentosd")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        settings = Settings.load()
    except (OSError, ValueError) as exc:
        log.error("failed to load configuration: %s", exc)
        raise SystemExit(1)
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
    try:
        server = AgentOSServer((settings.host, settings.port), runtime, gateway, settings.api_token)
    except OSError as exc:
        log.error("failed to bind %s:%s: %s", settings.host, settings.port, exc)
        raise SystemExit(1)
    log.info("agentosd listening on http://%s:%s", settings.host, settings.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupted, shutting down")
    finally:
        server.server_close()
