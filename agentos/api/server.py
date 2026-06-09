from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agentos.domain.models import Actor


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "AgentOS/0.1"

    def do_GET(self) -> None:
        if self.path == "/v1/health":
            self._reply(HTTPStatus.OK, {"status": "ok"})
        elif self.path == "/v1/agents":
            self._invoke(lambda: self.server.runtime.list_agents(self._actor()))
        elif self.path == "/v1/tools":
            self._reply(HTTPStatus.OK, self.server.runtime.tools.manifests())
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/v1/agents":
            body = self._body()
            self._invoke(
                lambda: self.server.runtime.register(
                    self._actor(), str(body["name"]), list(body.get("capabilities", []))
                ),
                HTTPStatus.CREATED,
            )
        elif self.path == "/v1/chat/completions":
            body = self._body()
            self._invoke(lambda: self.server.gateway.complete(self._actor(), body))
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _actor(self) -> Actor:
        actor_id = self.headers.get("x-agentos-actor", "local-user")
        roles = tuple(
            role.strip()
            for role in self.headers.get("x-agentos-roles", "administrator").split(",")
            if role.strip()
        )
        return Actor(actor_id, roles=roles)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length > 10 * 1024 * 1024:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _invoke(self, operation, success: HTTPStatus = HTTPStatus.OK) -> None:
        try:
            self._reply(success, operation())
        except PermissionError as error:
            self._reply(HTTPStatus.FORBIDDEN, {"error": "forbidden", "detail": str(error)})
        except (KeyError, ValueError, json.JSONDecodeError) as error:
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
        return


class AgentOSServer(ThreadingHTTPServer):
    def __init__(self, address, runtime, gateway):
        super().__init__(address, ApiHandler)
        self.runtime = runtime
        self.gateway = gateway
