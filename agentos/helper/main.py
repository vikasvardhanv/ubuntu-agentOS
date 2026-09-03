"""AgentOS privileged helper daemon.

Runs as root (systemd User=root). Listens on a Unix socket at
/run/agentos/helper.sock (mode 660, group agentos). Executes approved
OS-level actions after re-verifying policy with the main daemon.

Protocol: newline-delimited JSON.
Request:  {"id": "<uuid>", "type": "<action_type>", "params": {...},
           "approval_token": "<optional>", "agent_id": "<id>"}
Response: {"id": "<uuid>", "ok": true/false, "result": {...}, "error": ""}
"""
from __future__ import annotations

import grp
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

SOCKET_PATH = Path("/run/agentos/helper.sock")
DAEMON_API = os.environ.get("AGENTOS_API", "http://127.0.0.1:7788")
API_TOKEN = os.environ.get("AGENTOS_API_TOKEN", "")
MAX_READ_BYTES = 1024 * 1024  # 1 MB

# Commands blocked unconditionally (defense-in-depth: every run_command also
# requires policy approval, but these patterns are rejected even with a token).
# Patterns are regular expressions matched against the whitespace-normalized
# command string.
_DANGEROUS_PATTERNS = [
    # Recursive forced deletes aimed at the root filesystem or the user home.
    re.compile(r"rm\s+(-\w+\s+)*-[a-z]*r[a-z]*f[a-z]*\s+/(\*|\s|$)", re.I),
    re.compile(r"rm\s+(-\w+\s+)*-[a-z]*f[a-z]*r[a-z]*\s+/(\*|\s|$)", re.I),
    re.compile(r"rm\s+(-\w+\s+)*-[a-z]*r[a-z]*f[a-z]*\s+(~|\$HOME\b)", re.I),
    # Filesystem creation / raw disk writes.
    re.compile(r"\bmkfs(\.\w+)?\b"),
    re.compile(r"\bdd\b.*\bof=/dev/(sd|hd|vd|xvd|nvme|mmcblk)"),
    re.compile(r">\s*/dev/(sd|hd|vd|xvd|nvme|mmcblk)"),
    re.compile(r"\bwipefs\b"),
    # Fork bomb.
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    # Permission sweeps over the root tree.
    re.compile(r"chmod\s+-R\s+777\s+/(\s|$)"),
    re.compile(r"chown\s+-R\b"),
    # Power state changes belong to humans, not agents. Matched at command
    # position (start of the command or after a shell separator) so benign
    # mentions like "echo reboot scheduled" are not false-positives.
    re.compile(r"(^|[;&|]\s*)(sudo\s+)?(shutdown|poweroff|reboot|halt)\b"),
    re.compile(r"\bsystemctl\s+(reboot|poweroff|halt)\b"),
    re.compile(r"(^|[;&|]\s*)(sudo\s+)?init\s+(0|6)\b"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [helper] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("agentos.helper")


# ---------------------------------------------------------------------------
# Policy re-verification
# ---------------------------------------------------------------------------

def _verify_policy(action: str, agent_id: str, approval_token: str) -> bool:
    """Call POST /v1/policy/evaluate on the main daemon to re-verify the action."""
    body = json.dumps({
        "capability": action,
        "resource": agent_id,
        "risk": "privileged",
        "context": {
            "agent": {"trust_level": "operator"},
            "approval": approval_token or None,
        },
    }).encode()
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    try:
        req = urllib.request.Request(
            f"{DAEMON_API}/v1/policy/evaluate",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("result") == "allow"
    except Exception as exc:
        log.warning("Policy re-verification failed: %s", exc)
        # Fail closed — if we can't reach the daemon, deny.
        return False


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _dangerous_command(cmd: str) -> bool:
    normalized = " ".join(cmd.split())
    return any(pattern.search(normalized) for pattern in _DANGEROUS_PATTERNS)


def handle_run_command(params: dict[str, Any]) -> dict[str, Any]:
    command = str(params.get("command", ""))
    if not command:
        raise ValueError("'command' is required")
    if _dangerous_command(command):
        raise PermissionError(f"Blocked dangerous command: {command!r}")
    timeout = int(params.get("timeout", 30))
    proc = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }


def handle_read_file(params: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(params.get("path", "")))
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    stat = path.stat()
    if stat.st_size > MAX_READ_BYTES:
        raise ValueError(f"File too large ({stat.st_size} bytes, max {MAX_READ_BYTES})")
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"path": str(path), "content": content, "size": stat.st_size}


def handle_write_file(params: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(params.get("path", "")))
    content = str(params.get("content", ""))
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "bytes_written": len(content.encode("utf-8"))}


def handle_list_directory(params: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(params.get("path", "")))
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    entries = []
    for entry in sorted(path.iterdir()):
        try:
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        except OSError:
            entries.append({"name": entry.name, "type": "unknown", "size": 0, "modified": 0})
    return {"path": str(path), "entries": entries, "count": len(entries)}


def handle_launch_app(params: dict[str, Any]) -> dict[str, Any]:
    app_name = str(params.get("app", ""))
    if not app_name:
        raise ValueError("'app' is required")
    # Sanitize: only alphanumeric, hyphens, underscores, dots.
    if not all(c.isalnum() or c in "-_." for c in app_name):
        raise ValueError(f"Invalid app name: {app_name!r}")
    proc = subprocess.Popen(
        ["gtk-launch", app_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"app": app_name, "pid": proc.pid, "launched": True}


def handle_install_package(params: dict[str, Any]) -> dict[str, Any]:
    package = str(params.get("package", ""))
    if not package:
        raise ValueError("'package' is required")
    # Sanitize: only alphanumeric, hyphens, dots, plus.
    if not all(c.isalnum() or c in "-_.+" for c in package):
        raise ValueError(f"Invalid package name: {package!r}")
    proc = subprocess.run(
        ["apt-get", "install", "-y", package],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    return {
        "package": package,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4096:],
        "stderr": proc.stderr[-4096:],
        "installed": proc.returncode == 0,
    }


def _read_uptime_seconds() -> float:
    """Read system uptime from /proc (Linux). Returns 0.0 where unavailable."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def _read_memory_bytes() -> tuple[int, int]:
    """Read (total, available) memory from /proc/meminfo (Linux).

    Returns (0, 0) where /proc is unavailable so the endpoint degrades
    gracefully instead of failing on non-Linux development hosts.
    """
    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
        return meminfo.get("MemTotal", 0) * 1024, meminfo.get("MemAvailable", 0) * 1024
    except OSError:
        return 0, 0


def handle_get_system_info(_params: dict[str, Any]) -> dict[str, Any]:
    uptime_secs = _read_uptime_seconds()
    mem_total, mem_avail = _read_memory_bytes()
    mem_used = mem_total - mem_avail
    # disk
    disk = shutil.disk_usage("/")
    # cpu count
    cpu_count = os.cpu_count() or 1
    # load average
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0
    return {
        "hostname": platform.node(),
        "os": platform.system(),
        "kernel": platform.release(),
        "uptime_seconds": uptime_secs,
        "cpu_count": cpu_count,
        "load_avg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "memory": {
            "total_bytes": mem_total,
            "used_bytes": mem_used,
            "available_bytes": mem_avail,
            "percent_used": round(mem_used / mem_total * 100, 1) if mem_total else 0,
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent_used": round(disk.used / disk.total * 100, 1) if disk.total else 0,
        },
    }


# Actions that ALWAYS require a valid approval token (re-verified with daemon).
_REQUIRES_APPROVAL = {"run_command", "write_file", "install_package", "launch_app"}

_HANDLERS = {
    "run_command": handle_run_command,
    "read_file": handle_read_file,
    "write_file": handle_write_file,
    "list_directory": handle_list_directory,
    "launch_app": handle_launch_app,
    "install_package": handle_install_package,
    "get_system_info": handle_get_system_info,
}


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------

def _handle_request(raw: bytes) -> bytes:
    req: dict[str, Any] = {}
    try:
        req = json.loads(raw.decode("utf-8"))
        req_id = str(req.get("id", ""))
        action_type = str(req.get("type", ""))
        params = dict(req.get("params", {}))
        approval_token = str(req.get("approval_token", ""))
        agent_id = str(req.get("agent_id", ""))

        if action_type not in _HANDLERS:
            raise ValueError(f"Unknown action type: {action_type!r}")

        # Re-verify policy for sensitive actions.
        if action_type in _REQUIRES_APPROVAL:
            if not _verify_policy(action_type, agent_id, approval_token):
                raise PermissionError(
                    f"Policy denied action '{action_type}' for agent '{agent_id}'"
                )

        result = _HANDLERS[action_type](params)
        response = {"id": req_id, "ok": True, "result": result, "error": ""}
    except PermissionError as exc:
        response = {"id": req.get("id", ""), "ok": False, "result": {}, "error": str(exc)}
    except Exception as exc:
        log.exception("Error handling request: %s", exc)
        response = {"id": req.get("id", ""), "ok": False, "result": {}, "error": str(exc)}

    return (json.dumps(response) + "\n").encode("utf-8")


def _serve_client(conn: socket.socket, addr: Any) -> None:
    try:
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                response = _handle_request(line)
                conn.sendall(response)
                break
    except Exception as exc:
        log.warning("Client error from %s: %s", addr, exc)
    finally:
        conn.close()


def _setup_socket() -> socket.socket:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(SOCKET_PATH))
    SOCKET_PATH.chmod(0o660)
    # Set group ownership to 'agentos' if it exists.
    try:
        gid = grp.getgrnam("agentos").gr_gid
        os.chown(str(SOCKET_PATH), -1, gid)
    except (KeyError, OSError):
        pass
    sock.listen(32)
    return sock


def main() -> None:
    log.info("AgentOS privileged helper starting (pid %d)", os.getpid())
    sock = _setup_socket()
    log.info("Listening on %s", SOCKET_PATH)

    def _shutdown(signum: int, frame: Any) -> None:
        log.info("Received signal %d, shutting down", signum)
        sock.close()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        try:
            conn, addr = sock.accept()
            t = threading.Thread(target=_serve_client, args=(conn, addr), daemon=True)
            t.start()
        except OSError as exc:
            if exc.errno in (9, 22):  # EBADF / EINVAL — socket closed
                break
            log.error("Accept error: %s", exc)
            time.sleep(0.1)


if __name__ == "__main__":
    main()
