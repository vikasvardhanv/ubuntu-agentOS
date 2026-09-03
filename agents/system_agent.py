#!/usr/bin/env python3
"""AgentOS System Agent — system info and package installation.

Trust level: operator
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
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
AGENT_NAME = "system-agent"
CAPABILITIES = ["system_info"]
TRUST_LEVEL = "operator"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{AGENT_NAME}] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(AGENT_NAME)


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


def _call_helper(action_type: str, params: dict[str, Any],
                 approval_token: str = "", agent_id: str = "") -> dict[str, Any]:
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


def _local_system_info() -> dict[str, Any]:
    """Gather system info locally (fallback when helper not running)."""
    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
    except OSError:
        uptime_secs = 0.0

    mem_total = mem_avail = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    if parts[0] == "MemTotal:":
                        mem_total = int(parts[1]) * 1024
                    elif parts[0] == "MemAvailable:":
                        mem_avail = int(parts[1]) * 1024
    except OSError:
        pass

    disk = shutil.disk_usage("/")
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0

    return {
        "hostname": platform.node(),
        "os": platform.system(),
        "kernel": platform.release(),
        "uptime_seconds": uptime_secs,
        "cpu_count": os.cpu_count() or 1,
        "load_avg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "memory": {
            "total_bytes": mem_total,
            "used_bytes": mem_total - mem_avail,
            "available_bytes": mem_avail,
            "percent_used": round((mem_total - mem_avail) / mem_total * 100, 1) if mem_total else 0,
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent_used": round(disk.used / disk.total * 100, 1) if disk.total else 0,
        },
        "mode": "local",
    }


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
    action = str(payload.get("action", "get_system_info"))
    approval_token = str(payload.get("approval_token", ""))

    if action == "get_system_info":
        if HELPER_SOCK.exists():
            return _call_helper("get_system_info", {}, agent_id=agent_id)
        return _local_system_info()

    elif action == "install_package":
        package = str(payload.get("package", ""))
        if not package:
            raise ValueError("'package' is required for install_package")
        if not HELPER_SOCK.exists():
            raise RuntimeError("Privileged helper not running — cannot install packages")
        return _call_helper("install_package", {"package": package},
                            approval_token=approval_token, agent_id=agent_id)

    raise ValueError(f"Unknown action: {action!r}. Supported: get_system_info, install_package")


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
