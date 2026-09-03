#!/usr/bin/env python3
"""AgentOS Shell Agent — executes shell commands via the privileged helper.

Trust level: operator (needs approval for sensitive commands)
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

DAEMON_API = os.environ.get("AGENTOS_API", "http://127.0.0.1:7788")
API_TOKEN = os.environ.get("AGENTOS_API_TOKEN", "")
HELPER_SOCK = Path(os.environ.get("AGENTOS_HELPER_SOCK", "/run/agentos/helper.sock"))
POLL_INTERVAL = float(os.environ.get("AGENTOS_POLL_INTERVAL", "2"))
AGENT_NAME = "shell-agent"
CAPABILITIES = ["run_command"]
TRUST_LEVEL = "operator"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{AGENT_NAME}] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(AGENT_NAME)


# ---------------------------------------------------------------------------
# HTTP helpers (shared pattern across agents)
# ---------------------------------------------------------------------------

def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "X-AgentOS-Actor": AGENT_NAME,
        "X-AgentOS-Roles": "operator",
    }
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    if extra:
        h.update(extra)
    return h


def _get(path: str) -> Any:
    req = urllib.request.Request(f"{DAEMON_API}{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _post(path: str, body: dict[str, Any], method: str = "POST") -> Any:
    data = json.dumps(body).encode()
    h = _headers({"Content-Length": str(len(data))})
    req = urllib.request.Request(f"{DAEMON_API}{path}", data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Helper socket client
# ---------------------------------------------------------------------------

def _call_helper(action_type: str, params: dict[str, Any],
                 approval_token: str = "", agent_id: str = "") -> dict[str, Any]:
    """Send a request to the privileged helper and return the result."""
    req = {
        "id": str(uuid4()),
        "type": action_type,
        "params": params,
        "approval_token": approval_token,
        "agent_id": agent_id,
    }
    payload = (json.dumps(req) + "\n").encode("utf-8")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(HELPER_SOCK))
        sock.sendall(payload)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        response = json.loads(buf.split(b"\n")[0])
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "helper error"))
        return response.get("result", {})
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Registration + task execution
# ---------------------------------------------------------------------------

_agent_id: str | None = None


def _register() -> str:
    global _agent_id
    result = _post("/v1/agents/register", {
        "name": AGENT_NAME,
        "capabilities": CAPABILITIES,
        "trust_level": TRUST_LEVEL,
    })
    _agent_id = result["id"]
    log.info("Registered as agent_id=%s", _agent_id)
    return _agent_id


def _execute_task(task: dict[str, Any], agent_id: str) -> dict[str, Any]:
    payload = task.get("payload", {})
    command = payload.get("command", "")
    approval_token = payload.get("approval_token", "")

    if not command:
        raise ValueError("Task payload must include 'command'")

    if not HELPER_SOCK.exists():
        # Fail closed: never execute commands without the policy-mediating
        # privileged helper, even in development environments.
        raise RuntimeError(
            "Privileged helper not running — refusing to execute shell commands "
            "without policy mediation (start agentos-helper.service)"
        )

    return _call_helper("run_command", {"command": command},
                        approval_token=approval_token, agent_id=agent_id)


def _process_pending_tasks(agent_id: str) -> None:
    try:
        data = _get(f"/v1/agents/{agent_id}/tasks")
        tasks = data if isinstance(data, list) else data.get("data", [])
    except Exception as exc:
        log.debug("Could not fetch tasks: %s", exc)
        return

    for task in tasks:
        if task.get("state") != "pending":
            continue
        task_id = task["id"]
        log.info("Executing task %s", task_id)
        try:
            result = _execute_task(task, agent_id)
            _post(f"/v1/agents/{agent_id}/tasks/{task_id}", {
                "state": "completed", "result": result
            }, method="PATCH")
        except Exception as exc:
            log.error("Task %s failed: %s", task_id, exc)
            try:
                _post(f"/v1/agents/{agent_id}/tasks/{task_id}", {
                    "state": "failed", "error": str(exc)
                }, method="PATCH")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True


def _stop(signum: int, frame: Any) -> None:
    global _running
    log.info("Shutting down (signal %d)", signum)
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    agent_id: str | None = None
    while _running and agent_id is None:
        try:
            agent_id = _register()
        except Exception as exc:
            log.warning("Registration failed, retrying in 5s: %s", exc)
            time.sleep(5)

    log.info("%s ready (agent_id=%s)", AGENT_NAME, agent_id)
    while _running:
        try:
            _process_pending_tasks(agent_id)  # type: ignore[arg-type]
        except Exception as exc:
            log.error("Poll error: %s", exc)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
