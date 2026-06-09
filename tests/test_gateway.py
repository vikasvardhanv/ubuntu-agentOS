import os
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from agentos.audit.log import AuditLog
from agentos.domain.models import Actor
from agentos.gateway.client import AnthropicTransport, GatewayClient, OpenAITransport
from agentos.gateway.errors import FailureKind, GatewayUpstreamError, classify
from agentos.gateway.health import CircuitBreaker
from agentos.gateway.providers import ProviderRegistry
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

    def test_open_circuit_removes_provider(self):
        circuits = CircuitBreaker(threshold=1, cooldown=999)
        circuits.failure("ollama")
        with self.assertRaisesRegex(ValueError, "no provider"):
            Router(circuits=circuits).candidates("ollama:qwen3", RoutePolicy())

    def test_custom_remote_provider_requires_https(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "providers.json"
            path.write_text(json.dumps({"providers": {"bad": {"base_url": "http://example.com"}}}))
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                ProviderRegistry.from_file(path)


class GatewayTests(unittest.TestCase):
    def test_viewer_cannot_infer(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(
                Router(), PolicyEngine(), AuditLog(Path(directory) / "audit.jsonl")
            )
            with self.assertRaises(PermissionError):
                gateway.complete(
                    Actor("viewer", roles=("viewer",)),
                    {"model": "ollama:qwen3", "messages": [{"role": "user", "content": "hi"}]},
                )

    def test_gateway_rejects_empty_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(
                Router(), PolicyEngine(), AuditLog(Path(directory) / "audit.jsonl")
            )
            with self.assertRaisesRegex(ValueError, "non-empty"):
                gateway.complete(
                    Actor("operator", roles=("operator",)),
                    {"model": "ollama:qwen3", "messages": []},
                )

    def test_gateway_falls_back_after_retryable_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(
                Router(("ollama:backup",)),
                PolicyEngine(),
                AuditLog(Path(directory) / "audit.jsonl"),
                retries=0,
            )
            gateway.client.complete = Mock(side_effect=[
                GatewayUpstreamError(
                    "unavailable", FailureKind.SERVER, status=503, retryable=True, fallback=True
                ),
                {"choices": [], "usage": {}},
            ])
            result = gateway.complete(
                Actor("operator", roles=("operator",)),
                {"model": "ollama:primary", "messages": [{"role": "user", "content": "hi"}]},
            )
            self.assertEqual([], result["choices"])
            self.assertEqual(2, gateway.client.complete.call_count)


class TransportTests(unittest.TestCase):
    def test_anthropic_normalizes_tool_calls(self):
        transport = AnthropicTransport()
        raw = {
            "id": "msg_1",
            "content": [{"type": "tool_use", "id": "tool_1", "name": "read", "input": {"x": 1}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }
        result = transport._normalize(raw, "claude")
        self.assertEqual("tool_calls", result["choices"][0]["finish_reason"])
        self.assertEqual("read", result["choices"][0]["message"]["tool_calls"][0]["function"]["name"])
        self.assertEqual(5, result["usage"]["total_tokens"])

    def test_anthropic_converts_system_and_tool_result(self):
        system, messages = AnthropicTransport._messages([
            {"role": "system", "content": "policy"},
            {"role": "tool", "tool_call_id": "t1", "content": "done"},
        ])
        self.assertEqual("policy", system)
        self.assertEqual("tool_result", messages[0]["content"][0]["type"])

    def test_error_classifier_does_not_retry_bad_request(self):
        error = classify(400, "unknown parameter")
        self.assertEqual(FailureKind.REQUEST, error.kind)
        self.assertFalse(error.retryable)
        self.assertFalse(error.fallback)
