from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agentos.domain.models import Actor, PolicyRequest, Risk

log = logging.getLogger("agentos.api")

# Pre-compiled path patterns for dynamic segments.
_RE_AGENT = re.compile(r"^/v1/agents/([^/]+)$")
_RE_AGENT_TASKS = re.compile(r"^/v1/agents/([^/]+)/tasks$")
_RE_AGENT_TASK = re.compile(r"^/v1/agents/([^/]+)/tasks/([^/]+)$")
_RE_APPROVAL_DECISION = re.compile(r"^/v1/approvals/([^/]+)/decision$")
_RE_MARKETPLACE_INSTALL = re.compile(r"^/v1/marketplace/agents/([^/]+)/install$")


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "AgentOS/0.3"

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/health":
            self._reply(HTTPStatus.OK, self.server.gateway.health())
            return
        if not self._authenticated():
            self._reply(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        actor = self._actor()

        if path == "/v1/agents":
            self._invoke(lambda: self.server.runtime.list_agents(actor))
        elif path == "/v1/tools":
            self._reply(HTTPStatus.OK, self.server.runtime.tools.manifests())
        elif path == "/v1/models":
            self._invoke(lambda: self._list_models())
        elif path == "/v1/audit":
            self._invoke(lambda: self._query_audit())
        elif path == "/v1/approvals/pending":
            self._invoke(lambda: self.server.runtime.list_pending_approvals(actor))
        elif path == "/v1/marketplace/agents":
            self._invoke(lambda: self._list_marketplace_agents())
        elif m := _RE_AGENT.match(path):
            agent_id = m.group(1)
            self._invoke(lambda: self.server.runtime.get_agent(actor, agent_id))
        elif m := _RE_AGENT_TASKS.match(path):
            agent_id = m.group(1)
            self._invoke(lambda: self.server.runtime.list_tasks(actor, agent_id))
        elif m := _RE_AGENT_TASK.match(path):
            agent_id, task_id = m.group(1), m.group(2)
            self._invoke(lambda: self.server.runtime.get_task(actor, agent_id, task_id))
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # ------------------------------------------------------------------ POST

    def do_POST(self) -> None:
        if not self._authenticated():
            self._reply(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        path = urlparse(self.path).path
        actor = self._actor()
        body = self._read_body()
        if body is None:
            return

        if path in ("/v1/agents", "/v1/agents/register"):
            self._invoke(
                lambda: self.server.runtime.register(
                    actor,
                    str(body["name"]),
                    list(body.get("capabilities", [])),
                    str(body.get("trust_level", "user")),
                ),
                HTTPStatus.CREATED,
            )
        elif path == "/v1/chat/completions":
            self._invoke(lambda: self.server.gateway.complete(actor, body))
        elif path == "/v1/policy/evaluate":
            self._invoke(lambda: self._evaluate_policy(actor, body))
        elif path == "/v1/approvals/request":
            self._invoke(
                lambda: self.server.runtime.request_approval(
                    actor,
                    str(body["agent_id"]),
                    str(body["action"]),
                    str(body.get("resource", "")),
                    dict(body.get("context", {})),
                ),
                HTTPStatus.CREATED,
            )
        elif m := _RE_APPROVAL_DECISION.match(path):
            approval_id = m.group(1)
            approved = bool(body.get("approved", False))
            reason = str(body.get("reason", ""))
            self._invoke(
                lambda: self.server.runtime.decide_approval(actor, approval_id, approved, reason)
            )
        elif m := _RE_MARKETPLACE_INSTALL.match(path):
            agent_name = m.group(1)
            self._invoke(
                lambda: self._install_marketplace_agent(actor, agent_name),
                HTTPStatus.CREATED,
            )
        elif m := _RE_AGENT_TASKS.match(path):
            agent_id = m.group(1)
            self._invoke(
                lambda: self.server.runtime.submit_task(actor, agent_id, body),
                HTTPStatus.CREATED,
            )
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # ------------------------------------------------------------------ PATCH

    def do_PATCH(self) -> None:
        if not self._authenticated():
            self._reply(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        path = urlparse(self.path).path
        actor = self._actor()
        body = self._read_body()
        if body is None:
            return

        if m := _RE_AGENT_TASK.match(path):
            agent_id, task_id = m.group(1), m.group(2)
            result_raw = body.get("result")
            self._invoke(
                lambda: self.server.runtime.update_task(
                    actor,
                    agent_id,
                    task_id,
                    str(body.get("state", "")),
                    dict(result_raw) if isinstance(result_raw, dict) else None,
                    str(body.get("error", "")),
                )
            )
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # ------------------------------------------------------------------ DELETE

    def do_DELETE(self) -> None:
        if not self._authenticated():
            self._reply(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        path = urlparse(self.path).path
        actor = self._actor()

        if m := _RE_AGENT.match(path):
            agent_id = m.group(1)
            self._invoke(lambda: self.server.runtime.unregister(actor, agent_id))
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # ------------------------------------------------------------------ helpers

    def _list_models(self) -> dict[str, Any]:
        """Return available models from the currently configured provider."""
        from agentos.gateway.discovery import discover_models
        route = self.server.gateway.router.registry.selected_route
        if not route or ":" not in route:
            return {"object": "list", "data": []}
        provider_name, _ = route.split(":", 1)
        provider = self.server.gateway.router.registry.resolve(provider_name)
        secret = self.server.gateway.router.registry.credential(provider)
        models = discover_models(provider, secret)
        return {
            "object": "list",
            "data": [{"id": m, "object": "model"} for m in models],
        }

    def _list_marketplace_agents(self) -> dict[str, Any]:
        """Return available agents from the marketplace registry."""
        try:
            from agentos.marketplace.registry import MarketplaceRegistry
            reg = MarketplaceRegistry()
            agents = reg.list_agents()
        except Exception as exc:
            return {"object": "list", "data": [], "error": str(exc)}
        return {"object": "list", "data": agents, "count": len(agents)}

    def _install_marketplace_agent(self, actor: Actor, agent_name: str) -> dict[str, Any]:
        """Install an agent from the marketplace."""
        from agentos.marketplace.registry import MarketplaceRegistry
        from agentos.marketplace.installer import AgentInstaller
        reg = MarketplaceRegistry()
        manifest = reg.get_agent(agent_name)
        if manifest is None:
            raise KeyError(f"agent not found in marketplace: {agent_name}")
        installer = AgentInstaller()
        return installer.install(manifest)

    def _evaluate_policy(self, actor: Actor, body: dict[str, Any]) -> dict[str, Any]:
        """Evaluate an RBAC/ABAC policy request and return the decision."""
        # Accept 'action' as an alias for 'capability' (OpenAI-style callers).
        capability = str(body.get("capability", "") or body.get("action", ""))
        # Accept resource as either a plain string or an object with an 'id' field.
        resource_raw = body.get("resource", "")
        resource = str(resource_raw.get("id", "") if isinstance(resource_raw, dict) else resource_raw)
        risk_str = str(body.get("risk", "read"))
        context = dict(body.get("context", {}))
        if not capability:
            raise ValueError("'capability' or 'action' is required")
        try:
            risk = Risk(risk_str)
        except ValueError:
            raise ValueError(f"unknown risk level: {risk_str!r}")
        # Approval tokens must be validated against the runtime's approval
        # store before they can influence the decision. An unknown, expired,
        # consumed, or mismatched token is dropped so the policy engine sees
        # no approval and fails closed (REQUIRE_APPROVAL / DENY).
        approval = context.get("approval")
        if approval and not self.server.runtime.validate_approval(
            str(approval), capability, resource
        ):
            context.pop("approval", None)
        request = PolicyRequest(actor, capability, resource, risk, context)
        decision = self.server.gateway.policy.evaluate(request)
        return {
            "result": decision.result.value,
            "reason": decision.reason,
            "constraints": decision.constraints,
        }

    def _query_audit(self) -> dict[str, Any]:
        """Query the audit log. Supports ?limit=, ?offset=, ?actor_id=, ?event_type=."""
        qs = parse_qs(urlparse(self.path).query)
        limit = int(qs.get("limit", ["100"])[0])
        offset = int(qs.get("offset", ["0"])[0])
        actor_id = qs.get("actor_id", [""])[0]
        event_type = qs.get("event_type", [""])[0]
        correlation_id = qs.get("correlation_id", [""])[0]
        records = self.server.audit.query(
            limit=limit,
            offset=offset,
            actor_id=actor_id,
            event_type=event_type,
            correlation_id=correlation_id,
        )
        return {"object": "list", "data": records, "count": len(records)}

    def _actor(self) -> Actor:
        actor_id = self.headers.get("x-agentos-actor", "local-user")
        roles = tuple(
            role.strip()
            for role in self.headers.get("x-agentos-roles", "operator").split(",")
            if role.strip()
        )
        return Actor(actor_id, roles=roles)

    def _authenticated(self) -> bool:
        if not self.server.api_token:
            return True
        return self.headers.get("authorization", "") == f"Bearer {self.server.api_token}"

    def _read_body(self) -> dict[str, Any] | None:
        """Read and parse the request body; replies 400 and returns None on error."""
        try:
            return self._body()
        except ValueError as error:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": str(error)})
            return None

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            raise ValueError("invalid content-length header")
        if length < 0:
            raise ValueError("invalid content-length header")
        if length > 10 * 1024 * 1024:
            raise ValueError("request too large")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _invoke(self, operation, success: HTTPStatus = HTTPStatus.OK) -> None:
        try:
            result = operation()
            self._reply(success, result)
        except PermissionError as error:
            self._reply(HTTPStatus.FORBIDDEN, {"error": "forbidden", "detail": str(error)})
        except KeyError as error:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found", "detail": str(error)})
        except (ValueError, json.JSONDecodeError) as error:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": str(error)})
        except Exception as error:
            self._reply(
                HTTPStatus.BAD_GATEWAY,
                {"error": "operation_failed", "detail": str(error)},
            )

    def _reply(self, status: HTTPStatus, body: Any) -> None:
        encoded = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        # Route http.server access logs through the logging module instead of
        # dropping them, so production deployments get request observability.
        log.info("%s %s", self.address_string(), format % args)


class AgentOSServer(ThreadingHTTPServer):
    def __init__(self, address, runtime, gateway, api_token: str = ""):
        super().__init__(address, ApiHandler)
        self.runtime = runtime
        self.gateway = gateway
        self.audit = audit = runtime.audit  # expose for direct access in handlers
        self.api_token = api_token
