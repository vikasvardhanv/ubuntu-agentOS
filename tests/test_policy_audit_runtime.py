import json
import tempfile
import unittest
from pathlib import Path

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor, AuditEvent, Decision, PolicyRequest, Risk
from agentos.policy.engine import PolicyEngine
from agentos.runtime.service import AgentRuntime
from agentos.tools.registry import ToolRegistry


class PolicyTests(unittest.TestCase):
    def test_privileged_action_requires_approval(self):
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("admin", roles=("administrator",)),
                "system.package.install",
                "curl",
                Risk.PRIVILEGED,
            )
        )
        self.assertEqual(Decision.REQUIRE_APPROVAL, decision.result)

    def test_prohibited_action_is_always_denied(self):
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("admin", roles=("administrator",)),
                "audit.disable",
                "audit",
                Risk.PROHIBITED,
            )
        )
        self.assertEqual(Decision.DENY, decision.result)

    def test_rbac_viewer_cannot_infer(self):
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("viewer", roles=("viewer",)),
                "llm.infer",
                "openai:gpt-4",
                Risk.READ,
            )
        )
        self.assertEqual(Decision.DENY, decision.result)

    def test_rbac_operator_can_infer(self):
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "llm.infer",
                "openai:gpt-4",
                Risk.READ,
            )
        )
        self.assertEqual(Decision.ALLOW, decision.result)

    # ---------- ABAC tests ----------

    def test_abac_untrusted_agent_denied_llm_infer(self):
        """ABAC: untrusted agent context overrides operator RBAC grant."""
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "llm.infer",
                "openai:gpt-4",
                Risk.READ,
                context={"agent": {"trust_level": "untrusted"}},
            )
        )
        self.assertEqual(Decision.DENY, decision.result)
        self.assertIn("untrusted", decision.reason)

    def test_abac_untrusted_agent_denied_tool(self):
        """ABAC: untrusted agent cannot use any tool."""
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "tool.execute",
                "bash",
                Risk.MODIFY,
                context={"agent": {"trust_level": "untrusted"}},
            )
        )
        self.assertEqual(Decision.DENY, decision.result)

    def test_abac_high_sensitivity_requires_approval(self):
        """ABAC: high-sensitivity resource requires human approval even for admins."""
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("admin", roles=("administrator",)),
                "agent.read",
                "secret-agent",
                Risk.READ,
                context={"resource": {"sensitivity": "high"}},
            )
        )
        self.assertEqual(Decision.REQUIRE_APPROVAL, decision.result)

    def test_abac_sandboxed_agent_external_inference_requires_approval(self):
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "llm.infer",
                "openai:gpt-4",
                Risk.EXTERNAL,
                context={"agent": {"trust_level": "sandboxed"}},
            )
        )
        self.assertEqual(Decision.REQUIRE_APPROVAL, decision.result)

    def test_abac_sandboxed_agent_with_approval_allowed(self):
        """ABAC: sandboxed agent with valid approval token proceeds."""
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "llm.infer",
                "openai:gpt-4",
                Risk.EXTERNAL,
                context={
                    "agent": {"trust_level": "sandboxed"},
                    "approval": "tok-abc123",
                },
            )
        )
        self.assertEqual(Decision.ALLOW, decision.result)

    def test_abac_trusted_agent_read_allowed_without_approval(self):
        """ABAC: trusted agent with non-external risk passes without approval gate."""
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "llm.infer",
                "ollama:local-model",
                Risk.READ,
                context={"agent": {"trust_level": "trusted"}},
            )
        )
        self.assertEqual(Decision.ALLOW, decision.result)

    def test_abac_no_matching_rule_falls_through_to_risk_gate(self):
        """ABAC: when no ABAC rule fires, the risk gate is still applied."""
        decision = PolicyEngine().evaluate(
            PolicyRequest(
                Actor("operator", roles=("operator",)),
                "llm.infer",
                "openai:gpt-4",
                Risk.EXTERNAL,
            )
        )
        # No ABAC rule fires, but EXTERNAL risk requires approval.
        self.assertEqual(Decision.REQUIRE_APPROVAL, decision.result)


class AuditTests(unittest.TestCase):
    def test_events_form_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            log = AuditLog(path)
            first = log.append(AuditEvent("test.first", "user", {}))
            second = log.append(AuditEvent("test.second", "user", {}))
            self.assertEqual(first["hash"], second["previous_hash"])
            self.assertEqual(2, len(path.read_text().splitlines()))
            json.loads(path.read_text().splitlines()[0])

    def test_query_empty_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "audit.jsonl")
            self.assertEqual([], log.query())

    def test_query_returns_events(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "audit.jsonl")
            log.append(AuditEvent("a.first", "alice", {}))
            log.append(AuditEvent("b.second", "bob", {}))
            log.append(AuditEvent("a.third", "alice", {}))
            all_records = log.query()
            self.assertEqual(3, len(all_records))

    def test_query_filters_by_actor_id(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "audit.jsonl")
            log.append(AuditEvent("x", "alice", {}))
            log.append(AuditEvent("y", "bob", {}))
            log.append(AuditEvent("z", "alice", {}))
            alice_records = log.query(actor_id="alice")
            self.assertEqual(2, len(alice_records))
            self.assertTrue(all(r["actor_id"] == "alice" for r in alice_records))

    def test_query_filters_by_event_type(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "audit.jsonl")
            log.append(AuditEvent("agent.registered", "u", {}))
            log.append(AuditEvent("llm.completed", "u", {}))
            log.append(AuditEvent("agent.registered", "u", {}))
            results = log.query(event_type="agent.registered")
            self.assertEqual(2, len(results))

    def test_query_pagination(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "audit.jsonl")
            for i in range(10):
                log.append(AuditEvent(f"evt.{i}", "u", {}))
            page1 = log.query(limit=3, offset=0)
            page2 = log.query(limit=3, offset=3)
            self.assertEqual(3, len(page1))
            self.assertEqual(3, len(page2))
            # No overlap between pages.
            ids1 = {r["event_id"] for r in page1}
            ids2 = {r["event_id"] for r in page2}
            self.assertEqual(0, len(ids1 & ids2))


class RuntimeTests(unittest.TestCase):
    def test_register_and_list_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "file-agent", ["tool.read"])
            self.assertEqual("file-agent", created["name"])
            self.assertEqual(1, len(runtime.list_agents(actor)))

    def test_get_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "my-agent", [])
            fetched = runtime.get_agent(actor, created["id"])
            self.assertEqual(created["id"], fetched["id"])

    def test_get_agent_not_found(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            with self.assertRaises(KeyError):
                runtime.get_agent(actor, "nonexistent-id")

    def test_unregister_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "temp-agent", [])
            runtime.unregister(actor, created["id"])
            self.assertEqual(0, len(runtime.list_agents(actor)))

    def test_submit_and_get_task(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "worker", ["tool.read"])
            task = runtime.submit_task(
                actor, created["id"], {"capability": "some.tool", "arguments": {"x": 1}}
            )
            self.assertIn(task["state"], {"completed", "failed"})
            fetched = runtime.get_task(actor, created["id"], task["id"])
            self.assertEqual(task["id"], fetched["id"])

    def test_submit_task_missing_capability_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "worker", [])
            task = runtime.submit_task(actor, created["id"], {})
            self.assertEqual("failed", task["state"])
            self.assertIn("capability", task["error"])

    def test_submit_task_to_missing_agent_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            with self.assertRaises(KeyError):
                runtime.submit_task(actor, "bad-id", {"capability": "x"})

    def test_viewer_cannot_submit_task(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            admin = Actor("admin", roles=("administrator",))
            viewer = Actor("viewer", roles=("viewer",))
            created = runtime.register(admin, "worker", [])
            with self.assertRaises(PermissionError):
                runtime.submit_task(viewer, created["id"], {"capability": "x"})

    def test_update_task_completes_pending_task(self):
        from agentos.runtime.service import Task

        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "worker", [])
            task = Task(agent_id=created["id"], payload={"capability": "x"})
            runtime._tasks[task.id] = task
            updated = runtime.update_task(
                actor, created["id"], task.id, "completed", result={"ok": True}
            )
            self.assertEqual("completed", updated["state"])
            self.assertEqual({"ok": True}, updated["result"])

    def test_update_task_rejects_terminal_task(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "worker", ["tool.read"])
            task = runtime.submit_task(actor, created["id"], {"capability": "x"})
            self.assertIn(task["state"], {"completed", "failed"})
            with self.assertRaises(ValueError):
                runtime.update_task(actor, created["id"], task["id"], "completed")

    def test_update_task_rejects_invalid_state(self):
        from agentos.runtime.service import Task

        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "worker", [])
            task = Task(agent_id=created["id"], payload={})
            runtime._tasks[task.id] = task
            with self.assertRaises(ValueError):
                runtime.update_task(actor, created["id"], task.id, "exploded")

    def test_viewer_cannot_update_task(self):
        from agentos.runtime.service import Task

        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            admin = Actor("admin", roles=("administrator",))
            viewer = Actor("viewer", roles=("viewer",))
            created = runtime.register(admin, "worker", [])
            task = Task(agent_id=created["id"], payload={})
            runtime._tasks[task.id] = task
            with self.assertRaises(PermissionError):
                runtime.update_task(viewer, created["id"], task.id, "completed")
