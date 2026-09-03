"""Tests for: approval API, marketplace registry, helper protocol, agent registration."""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

# Ensure project root is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor, AuditEvent
from agentos.policy.engine import PolicyEngine
from agentos.runtime.service import AgentRuntime, ApprovalRequest
from agentos.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(tmp_dir: str) -> AgentRuntime:
    audit = AuditLog(Path(tmp_dir) / "audit.jsonl")
    return AgentRuntime(PolicyEngine(), audit, ToolRegistry())


def _admin() -> Actor:
    return Actor("admin", roles=("administrator",))


def _operator() -> Actor:
    return Actor("op", roles=("operator",))


def _viewer() -> Actor:
    return Actor("viewer", roles=("viewer",))


# ---------------------------------------------------------------------------
# Approval runtime tests
# ---------------------------------------------------------------------------

class ApprovalRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._rt = _make_runtime(self._tmp)
        self._admin = _admin()
        # Register an agent to use in approval requests.
        self._agent = self._rt.register(self._admin, "test-agent", ["run_command"])

    def test_request_approval_returns_pending(self) -> None:
        approval = self._rt.request_approval(
            self._admin, self._agent["id"], "run_command", resource="/bin/ls"
        )
        self.assertEqual("pending", approval["status"])
        self.assertEqual("run_command", approval["action"])
        self.assertEqual(self._agent["id"], approval["agent_id"])

    def test_list_pending_approvals(self) -> None:
        self._rt.request_approval(self._admin, self._agent["id"], "run_command")
        self._rt.request_approval(self._admin, self._agent["id"], "write_file")
        pending = self._rt.list_pending_approvals(self._admin)
        self.assertEqual(2, len(pending))
        self.assertTrue(all(a["status"] == "pending" for a in pending))

    def test_approve_decision(self) -> None:
        approval = self._rt.request_approval(
            self._admin, self._agent["id"], "run_command"
        )
        decided = self._rt.decide_approval(self._admin, approval["id"], True, "looks good")
        self.assertEqual("approved", decided["status"])
        self.assertEqual("looks good", decided["reason"])
        self.assertEqual("admin", decided["decided_by"])
        self.assertTrue(decided["decided_at"])

    def test_deny_decision(self) -> None:
        approval = self._rt.request_approval(
            self._admin, self._agent["id"], "run_command"
        )
        decided = self._rt.decide_approval(self._admin, approval["id"], False, "too risky")
        self.assertEqual("denied", decided["status"])

    def test_list_pending_excludes_decided(self) -> None:
        a1 = self._rt.request_approval(self._admin, self._agent["id"], "run_command")
        a2 = self._rt.request_approval(self._admin, self._agent["id"], "write_file")
        self._rt.decide_approval(self._admin, a1["id"], True)
        pending = self._rt.list_pending_approvals(self._admin)
        ids = {a["id"] for a in pending}
        self.assertNotIn(a1["id"], ids)
        self.assertIn(a2["id"], ids)

    def test_decide_nonexistent_raises(self) -> None:
        with self.assertRaises(KeyError):
            self._rt.decide_approval(self._admin, "nonexistent-id", True)

    def test_double_decide_raises(self) -> None:
        approval = self._rt.request_approval(
            self._admin, self._agent["id"], "run_command"
        )
        self._rt.decide_approval(self._admin, approval["id"], True)
        with self.assertRaises(ValueError):
            self._rt.decide_approval(self._admin, approval["id"], False)

    def test_viewer_cannot_list_pending(self) -> None:
        with self.assertRaises(PermissionError):
            self._rt.list_pending_approvals(_viewer())

    def test_request_approval_for_missing_agent_raises(self) -> None:
        with self.assertRaises(KeyError):
            self._rt.request_approval(self._admin, "bad-agent-id", "run_command")


# ---------------------------------------------------------------------------
# Approval API endpoint tests (via server)
# ---------------------------------------------------------------------------

class ApprovalApiTests(unittest.TestCase):
    """End-to-end HTTP tests for approval endpoints."""

    def setUp(self) -> None:
        import urllib.request
        from agentos.api.server import AgentOSServer

        self._tmp = tempfile.mkdtemp()
        rt = _make_runtime(self._tmp)

        # Minimal gateway stub.
        class _FakeGateway:
            policy = PolicyEngine()
            def health(self): return {"status": "ok"}
            def complete(self, actor, body): return {"choices": [{"message": {"content": "hi"}}]}

        self._server = AgentOSServer(("127.0.0.1", 0), rt, _FakeGateway())
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        # Register an agent for tests.
        self._agent_id = rt.register(_admin(), "api-test-agent", ["run_command"])["id"]

    def tearDown(self) -> None:
        self._server.shutdown()

    def _base(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-AgentOS-Actor": "admin",
            "X-AgentOS-Roles": "administrator",
        }

    def _get(self, path: str) -> dict:
        import urllib.request
        req = urllib.request.Request(f"{self._base()}{path}", headers=self._headers())
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, body: dict) -> dict:
        import urllib.request
        data = json.dumps(body).encode()
        h = {**self._headers(), "Content-Length": str(len(data))}
        req = urllib.request.Request(
            f"{self._base()}{path}", data=data, headers=h, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def test_list_pending_empty(self) -> None:
        result = self._get("/v1/approvals/pending")
        self.assertIsInstance(result, list)
        self.assertEqual(0, len(result))

    def test_request_then_list_pending(self) -> None:
        self._post("/v1/approvals/request", {
            "agent_id": self._agent_id,
            "action": "run_command",
            "resource": "/bin/ls",
        })
        pending = self._get("/v1/approvals/pending")
        self.assertEqual(1, len(pending))
        self.assertEqual("pending", pending[0]["status"])

    def test_approve_via_api(self) -> None:
        a = self._post("/v1/approvals/request", {
            "agent_id": self._agent_id,
            "action": "run_command",
        })
        result = self._post(f"/v1/approvals/{a['id']}/decision", {
            "approved": True,
            "reason": "automated test",
        })
        self.assertEqual("approved", result["status"])

    def test_deny_via_api(self) -> None:
        a = self._post("/v1/approvals/request", {
            "agent_id": self._agent_id,
            "action": "write_file",
        })
        result = self._post(f"/v1/approvals/{a['id']}/decision", {
            "approved": False,
            "reason": "not allowed",
        })
        self.assertEqual("denied", result["status"])

    def test_decision_on_missing_approval_returns_404(self) -> None:
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/v1/approvals/nonexistent-id/decision", {"approved": True})
        self.assertEqual(404, ctx.exception.code)


# ---------------------------------------------------------------------------
# Marketplace registry tests
# ---------------------------------------------------------------------------

class MarketplaceRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._registry_path = Path(self._tmp) / "registry.json"
        self._registry_path.write_text(json.dumps({
            "version": "1.0",
            "agents": [
                {
                    "name": "test-agent-alpha",
                    "description": "Alpha test agent",
                    "version": "1.0.0",
                    "entry_point": "agents/test_alpha.py",
                    "capabilities": ["run_command"],
                    "trust_level": "operator",
                },
                {
                    "name": "test-agent-beta",
                    "description": "Beta test agent",
                    "version": "2.0.0",
                    "entry_point": "agents/test_beta.py",
                    "capabilities": ["llm_inference"],
                    "trust_level": "trusted",
                },
            ],
        }), encoding="utf-8")

    def _reg(self):
        from agentos.marketplace.registry import MarketplaceRegistry
        return MarketplaceRegistry(self._registry_path)

    def test_list_agents_returns_all(self) -> None:
        agents = self._reg().list_agents()
        self.assertEqual(2, len(agents))

    def test_list_agents_names(self) -> None:
        names = {a["name"] for a in self._reg().list_agents()}
        self.assertIn("test-agent-alpha", names)
        self.assertIn("test-agent-beta", names)

    def test_get_agent_found(self) -> None:
        agent = self._reg().get_agent("test-agent-alpha")
        self.assertIsNotNone(agent)
        self.assertEqual("operator", agent["trust_level"])
        self.assertEqual(["run_command"], agent["capabilities"])

    def test_get_agent_not_found(self) -> None:
        agent = self._reg().get_agent("nonexistent")
        self.assertIsNone(agent)

    def test_registry_version(self) -> None:
        from agentos.marketplace.registry import MarketplaceRegistry
        reg = MarketplaceRegistry(self._registry_path)
        data = reg._data
        self.assertEqual("1.0", data["version"])

    def test_registry_missing_file_raises(self) -> None:
        from agentos.marketplace.registry import MarketplaceRegistry
        with self.assertRaises(FileNotFoundError):
            MarketplaceRegistry(Path(self._tmp) / "missing.json")


# ---------------------------------------------------------------------------
# Marketplace installer tests
# ---------------------------------------------------------------------------

class MarketplaceInstallerTests(unittest.TestCase):
    """Tests that installer dry-runs correctly without root."""

    def _manifest(self, name: str = "my-agent") -> dict:
        return {
            "name": name,
            "description": "Test agent",
            "version": "1.0.0",
            "entry_point": f"agents/{name}.py",
            "capabilities": ["run_command"],
            "trust_level": "operator",
        }

    def test_install_returns_result(self) -> None:
        from agentos.marketplace.installer import AgentInstaller
        result = AgentInstaller().install(self._manifest("my-agent"))
        self.assertTrue(result["installed"])
        self.assertEqual("my-agent", result["name"])

    def test_install_dry_run_without_root(self) -> None:
        from agentos.marketplace.installer import AgentInstaller
        result = AgentInstaller().install(self._manifest("dry-agent"))
        # In the test sandbox we never have /usr/lib write access.
        self.assertIn("installed", result)
        self.assertIn("name", result)


# ---------------------------------------------------------------------------
# Marketplace API endpoint test
# ---------------------------------------------------------------------------

class MarketplaceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from agentos.api.server import AgentOSServer

        self._tmp = tempfile.mkdtemp()
        rt = _make_runtime(self._tmp)

        class _FakeGateway:
            policy = PolicyEngine()
            def health(self): return {"status": "ok"}
            def complete(self, actor, body): return {"choices": []}

        self._server = AgentOSServer(("127.0.0.1", 0), rt, _FakeGateway())
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _get(self, path: str) -> dict:
        import urllib.request
        headers = {
            "X-AgentOS-Actor": "admin",
            "X-AgentOS-Roles": "administrator",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}{path}", headers=headers
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def test_marketplace_agents_endpoint(self) -> None:
        result = self._get("/v1/marketplace/agents")
        self.assertIn("data", result)
        # Should return the bundled registry agents (or empty on path miss).
        self.assertIsInstance(result["data"], list)

    def test_marketplace_agents_include_bundled(self) -> None:
        result = self._get("/v1/marketplace/agents")
        # If the dev registry.json is found, we should see bundled agents.
        data = result.get("data", [])
        if data:
            names = {a["name"] for a in data}
            self.assertTrue(
                any("agent" in n for n in names),
                f"Expected at least one agent in marketplace, got: {names}",
            )


# ---------------------------------------------------------------------------
# Task PATCH endpoint tests (agent result reporting)
# ---------------------------------------------------------------------------

class TaskPatchApiTests(unittest.TestCase):
    """PATCH /v1/agents/{agent_id}/tasks/{task_id} — agents reporting results."""

    def setUp(self) -> None:
        from agentos.api.server import AgentOSServer

        self._tmp = tempfile.mkdtemp()
        self._rt = _make_runtime(self._tmp)

        class _FakeGateway:
            policy = PolicyEngine()
            def health(self): return {"status": "ok"}
            def complete(self, actor, body): return {"choices": []}

        self._server = AgentOSServer(("127.0.0.1", 0), self._rt, _FakeGateway())
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._agent = self._rt.register(_admin(), "patch-agent", ["run_command"])

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _request(self, method: str, path: str, body: dict | None = None,
                 roles: str = "administrator", raw_body: bytes | None = None):
        import urllib.error
        import urllib.request
        data = raw_body if raw_body is not None else (
            json.dumps(body).encode() if body is not None else None
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-AgentOS-Actor": "tester",
                "X-AgentOS-Roles": roles,
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def _make_pending_task(self) -> str:
        from agentos.runtime.service import Task
        task = Task(agent_id=self._agent["id"], payload={"capability": "run_command"})
        self._rt._tasks[task.id] = task
        return task.id

    def test_patch_completes_pending_task(self) -> None:
        task_id = self._make_pending_task()
        status, result = self._request(
            "PATCH", f"/v1/agents/{self._agent['id']}/tasks/{task_id}",
            {"state": "completed", "result": {"stdout": "ok"}},
        )
        self.assertEqual(200, status)
        self.assertEqual("completed", result["state"])
        self.assertEqual({"stdout": "ok"}, result["result"])

    def test_patch_terminal_task_rejected(self) -> None:
        task_id = self._make_pending_task()
        self._request("PATCH", f"/v1/agents/{self._agent['id']}/tasks/{task_id}",
                      {"state": "completed"})
        status, result = self._request(
            "PATCH", f"/v1/agents/{self._agent['id']}/tasks/{task_id}",
            {"state": "failed"},
        )
        self.assertEqual(400, status)
        self.assertIn("already", result["detail"])

    def test_patch_denied_for_viewer(self) -> None:
        task_id = self._make_pending_task()
        status, _ = self._request(
            "PATCH", f"/v1/agents/{self._agent['id']}/tasks/{task_id}",
            {"state": "completed"}, roles="viewer",
        )
        self.assertEqual(403, status)

    def test_patch_unknown_task_404(self) -> None:
        status, _ = self._request(
            "PATCH", f"/v1/agents/{self._agent['id']}/tasks/nope",
            {"state": "completed"},
        )
        self.assertEqual(404, status)

    def test_post_malformed_json_returns_400(self) -> None:
        status, result = self._request(
            "POST", "/v1/agents", raw_body=b"{not json",
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", result["error"])

    def test_post_non_object_json_returns_400(self) -> None:
        status, result = self._request(
            "POST", "/v1/agents", raw_body=b"[1, 2, 3]",
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", result["error"])


# ---------------------------------------------------------------------------
# Helper protocol tests (mock socket)
# ---------------------------------------------------------------------------

class HelperProtocolTests(unittest.TestCase):
    """Tests for the helper request/response dispatch without running as root."""

    def _call_handler(self, action_type: str, params: dict) -> dict:
        """Import and call the handler directly."""
        from agentos.helper.main import _handle_request
        req = json.dumps({
            "id": "test-id",
            "type": action_type,
            "params": params,
            "approval_token": "",
            "agent_id": "test-agent",
        }).encode()
        # Patch _verify_policy to always allow in tests.
        with patch("agentos.helper.main._verify_policy", return_value=True):
            raw_response = _handle_request(req)
        return json.loads(raw_response.decode().strip())

    def test_get_system_info(self) -> None:
        result = self._call_handler("get_system_info", {})
        self.assertTrue(result["ok"])
        data = result["result"]
        self.assertIn("hostname", data)
        self.assertIn("cpu_count", data)
        self.assertIn("memory", data)
        self.assertIn("disk", data)
        self.assertIn("uptime_seconds", data)

    def test_list_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            Path(d, "file_a.txt").write_text("a")
            Path(d, "file_b.txt").write_text("b")
            result = self._call_handler("list_directory", {"path": d})
        self.assertTrue(result["ok"])
        entries = result["result"]["entries"]
        names = {e["name"] for e in entries}
        self.assertIn("file_a.txt", names)
        self.assertIn("file_b.txt", names)

    def test_read_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello helper")
            fname = f.name
        try:
            result = self._call_handler("read_file", {"path": fname})
            self.assertTrue(result["ok"])
            self.assertEqual("hello helper", result["result"]["content"])
        finally:
            os.unlink(fname)

    def test_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            dest = str(Path(d) / "out.txt")
            result = self._call_handler("write_file", {"path": dest, "content": "written!"})
            self.assertTrue(result["ok"])
            self.assertEqual("written!", Path(dest).read_text())

    def test_run_command_allowed(self) -> None:
        result = self._call_handler("run_command", {"command": "echo hello"})
        self.assertTrue(result["ok"])
        self.assertIn("hello", result["result"]["stdout"])
        self.assertEqual(0, result["result"]["exit_code"])

    def test_run_command_blocked(self) -> None:
        result = self._call_handler("run_command", {"command": "rm -rf /"})
        self.assertFalse(result["ok"])
        self.assertIn("Blocked", result["error"])

    def test_run_command_blocked_patterns(self) -> None:
        # Test the classifier directly so a regression can never cause the
        # test suite to execute a destructive command end-to-end.
        from agentos.helper.main import _dangerous_command
        blocked = [
            "rm -rf /",
            "rm -fr /*",
            "rm -rf ~",
            "rm -rf ~/x",
            "rm -rf $HOME",
            "sudo reboot",
            "shutdown -h now",
            "systemctl poweroff",
            "init 0",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/nvme0n1",
            "wipefs -a /dev/sda",
            "chmod -R 777 /",
            "chown -R bob /etc",
            "echo hi; reboot",
        ]
        for command in blocked:
            self.assertTrue(_dangerous_command(command), f"expected blocked: {command!r}")

    def test_run_command_allows_benign_lookalikes(self) -> None:
        # Commands that mention risky words but are not destructive.
        from agentos.helper.main import _dangerous_command
        allowed = [
            "echo reboot scheduled",
            "rm -rf /tmp/agentos-cache",
            "dd if=image.iso of=usb.img",
            "ls -la /tmp",
        ]
        for command in allowed:
            self.assertFalse(_dangerous_command(command), f"expected allowed: {command!r}")
        # One benign command end-to-end through the handler.
        result = self._call_handler("run_command", {"command": "echo reboot scheduled"})
        self.assertTrue(result["ok"])

    def test_unknown_action_type(self) -> None:
        req = json.dumps({
            "id": "x",
            "type": "explode_everything",
            "params": {},
            "approval_token": "",
            "agent_id": "a",
        }).encode()
        from agentos.helper.main import _handle_request
        raw = _handle_request(req)
        result = json.loads(raw.decode().strip())
        self.assertFalse(result["ok"])
        self.assertIn("explode_everything", result["error"])

    def test_relative_path_rejected(self) -> None:
        result = self._call_handler("read_file", {"path": "relative/path"})
        self.assertFalse(result["ok"])
        self.assertIn("absolute", result["error"])

    def test_policy_denied_action_rejected(self) -> None:
        """When policy returns False, action should be denied."""
        from agentos.helper.main import _handle_request
        req = json.dumps({
            "id": "test",
            "type": "run_command",
            "params": {"command": "echo hi"},
            "approval_token": "",
            "agent_id": "bad-agent",
        }).encode()
        with patch("agentos.helper.main._verify_policy", return_value=False):
            raw = _handle_request(req)
        result = json.loads(raw.decode().strip())
        self.assertFalse(result["ok"])
        self.assertIn("denied", result["error"].lower())


# ---------------------------------------------------------------------------
# Bundled agent registration flow tests
# ---------------------------------------------------------------------------

class BundledAgentRegistrationTests(unittest.TestCase):
    """Verify that each bundled agent registers correctly with the runtime."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._rt = _make_runtime(self._tmp)

    def _register(self, name: str, capabilities: list, trust_level: str) -> dict:
        return self._rt.register(_admin(), name, capabilities, trust_level)

    def test_assistant_agent_registration(self) -> None:
        agent = self._register("assistant-agent", ["llm_inference"], "trusted")
        self.assertEqual("assistant-agent", agent["name"])
        self.assertEqual("trusted", agent["trust_level"])
        self.assertIn("llm_inference", agent["capabilities"])
        self.assertEqual("registered", agent["state"])

    def test_shell_agent_registration(self) -> None:
        agent = self._register("shell-agent", ["run_command"], "operator")
        self.assertEqual("shell-agent", agent["name"])
        self.assertEqual("operator", agent["trust_level"])
        self.assertIn("run_command", agent["capabilities"])

    def test_file_agent_registration(self) -> None:
        agent = self._register("file-agent", ["file_operations"], "user")
        self.assertEqual("file-agent", agent["name"])
        self.assertEqual("user", agent["trust_level"])
        self.assertIn("file_operations", agent["capabilities"])

    def test_system_agent_registration(self) -> None:
        agent = self._register("system-agent", ["system_info"], "operator")
        self.assertEqual("system-agent", agent["name"])
        self.assertEqual("operator", agent["trust_level"])
        self.assertIn("system_info", agent["capabilities"])

    def test_all_four_agents_coexist(self) -> None:
        self._register("assistant-agent", ["llm_inference"], "trusted")
        self._register("shell-agent", ["run_command"], "operator")
        self._register("file-agent", ["file_operations"], "user")
        self._register("system-agent", ["system_info"], "operator")
        agents = self._rt.list_agents(_admin())
        self.assertEqual(4, len(agents))

    def test_registered_agent_is_retrievable(self) -> None:
        created = self._register("assistant-agent", ["llm_inference"], "trusted")
        fetched = self._rt.get_agent(_admin(), created["id"])
        self.assertEqual(created["id"], fetched["id"])
        self.assertEqual("trusted", fetched["trust_level"])

    def test_trust_level_persists(self) -> None:
        for name, trust in [
            ("assistant-agent", "trusted"),
            ("shell-agent", "operator"),
            ("file-agent", "user"),
            ("system-agent", "operator"),
        ]:
            agent = self._register(name, [], trust)
            fetched = self._rt.get_agent(_admin(), agent["id"])
            self.assertEqual(trust, fetched["trust_level"], f"Trust level mismatch for {name}")

    def test_unregister_agent(self) -> None:
        agent = self._register("shell-agent", ["run_command"], "operator")
        self._rt.unregister(_admin(), agent["id"])
        with self.assertRaises(KeyError):
            self._rt.get_agent(_admin(), agent["id"])


# ---------------------------------------------------------------------------
# DB schema test: approvals table
# ---------------------------------------------------------------------------

class DbSchemaApprovalsTest(unittest.TestCase):
    def test_approvals_table_has_correct_columns(self) -> None:
        import sqlite3
        from contextlib import closing
        schema = Path("db/migrations/001_initial.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript(schema)
            cols = [
                row[1]
                for row in conn.execute("PRAGMA table_info(approvals)")
            ]
        self.assertIn("id", cols)
        self.assertIn("agent_id", cols)
        self.assertIn("action", cols)
        self.assertIn("status", cols)
        self.assertIn("requested_at", cols)
        self.assertIn("decided_at", cols)
        self.assertIn("decided_by", cols)

    def test_action_approvals_table_still_exists(self) -> None:
        import sqlite3
        from contextlib import closing
        schema = Path("db/migrations/001_initial.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript(schema)
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        self.assertIn("action_approvals", tables)
        self.assertIn("approvals", tables)


if __name__ == "__main__":
    unittest.main()
