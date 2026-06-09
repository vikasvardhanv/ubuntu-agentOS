import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor
from agentos.gateway.router import RoutePolicy, Router
from agentos.gateway.service import Gateway
from agentos.policy.engine import PolicyEngine


class RouterTests(unittest.TestCase):
    def test_local_only_skips_remote_fallback(self):
        router = Router(("openrouter:remote", "ollama:qwen3"))
        routes = router.candidates("ollama:llama3", RoutePolicy(local_only=True))
        self.assertEqual(["ollama", "ollama"], [route.provider.id for route in routes])

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret"})
    def test_fallback_is_ordered_and_deduplicated(self):
        router = Router(("openrouter:backup", "openrouter:backup"))
        routes = router.candidates("openrouter:primary", RoutePolicy())
        self.assertEqual(["primary", "backup"], [route.model for route in routes])

    def test_remote_route_without_credentials_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "no provider"):
                Router().candidates("openai:gpt", RoutePolicy())


class GatewayTests(unittest.TestCase):
    def test_viewer_cannot_infer(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(
                Router(), PolicyEngine(), AuditLog(Path(directory) / "audit.jsonl")
            )
            with self.assertRaises(PermissionError):
                gateway.complete(Actor("viewer", roles=("viewer",)), {"model": "ollama:qwen3"})
