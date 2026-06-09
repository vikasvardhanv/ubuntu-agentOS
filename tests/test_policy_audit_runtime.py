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


class RuntimeTests(unittest.TestCase):
    def test_register_and_list_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            runtime = AgentRuntime(PolicyEngine(), audit, ToolRegistry())
            actor = Actor("admin", roles=("administrator",))
            created = runtime.register(actor, "file-agent", ["tool.read"])
            self.assertEqual("file-agent", created["name"])
            self.assertEqual(1, len(runtime.list_agents(actor)))
