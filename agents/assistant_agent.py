#!/usr/bin/env python3
"""AgentOS Assistant Agent — conversational LLM inference agent.

Registers with the runtime as the 'assistant-agent', polls for tasks that
contain a 'messages' array, calls POST /v1/chat/completions, and posts the
result back.  This is what the desktop shell's Chat panel talks to.

Trust level: trusted
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import urllib.request
from typing import Any

DAEMON_API = os.environ.get("AGENTOS_API", "http://127.0.0.1:7788")
API_TOKEN = os.environ.get("AGENTOS_API_TOKEN", "")
POLL_INTERVAL = float(os.environ.get("AGENTOS_POLL_INTERVAL", "2"))
AGENT_NAME = "assistant-agent"
CAPABILITIES = ["llm_inference"]
TRUST_LEVEL = "trusted"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{AGENT_NAME}] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(AGENT_NAME)


# ---------------------------------------------------------------------------
# HTTP helpers
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
# Registration
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


# ---------------------------------------------------------------------------
# Task execution
# ---------------------------------------------------------------------------

def _execute_task(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("payload", {})
    messages = payload.get("messages", [])
    model = payload.get("model", "")
    system_prompt = payload.get("system_prompt", (
        "You are AgentOS Assistant, an AI agent running on the user's desktop. "
        "Be helpful, concise, and accurate."
    ))

    if not messages:
        raise ValueError("Task payload must include 'messages'")

    # Prepend system message if not already present.
    full_messages = list(messages)
    if not full_messages or full_messages[0].get("role") != "system":
        full_messages.insert(0, {"role": "system", "content": system_prompt})

    chat_body: dict[str, Any] = {"messages": full_messages}
    if model:
        chat_body["model"] = model

    result = _post("/v1/chat/completions", chat_body)
    return {"response": result}


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
            result = _execute_task(task)
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
