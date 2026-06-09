from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from agentos.gateway.errors import FailureKind, GatewayUpstreamError, classify
from agentos.gateway.router import Route


class Transport(ABC):
    @abstractmethod
    def complete(self, route: Route, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        ...

    @staticmethod
    def request(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            message = error.read().decode(errors="replace")[:4096]
            raise classify(error.code, message) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise GatewayUpstreamError(
                str(error), FailureKind.TIMEOUT, retryable=True, fallback=True
            ) from error
        except json.JSONDecodeError as error:
            raise GatewayUpstreamError(
                "provider returned invalid JSON", FailureKind.SERVER, retryable=True
            ) from error


class OpenAITransport(Transport):
    def complete(self, route: Route, payload: dict[str, Any], timeout: float) -> dict:
        body = _clean_payload(payload)
        body["model"] = route.model
        if route.provider.metadata.get("aggregator"):
            policy = payload.get("route_policy") or {}
            body["provider"] = {
                "only": policy.get("upstream_only"),
                "ignore": policy.get("upstream_ignore"),
                "sort": policy.get("sort"),
                "require_parameters": bool(policy.get("require_parameters", False)),
                "data_collection": policy.get("data_collection", "deny"),
            }
            body["provider"] = {key: value for key, value in body["provider"].items() if value}
        result = self.request(
            f"{route.provider.base_url.rstrip('/')}/chat/completions",
            body,
            _headers(route, bearer=True),
            timeout,
        )
        if not isinstance(result.get("choices"), list):
            raise GatewayUpstreamError(
                "provider response has no choices",
                FailureKind.SERVER,
                retryable=True,
                fallback=True,
            )
        return result


class AnthropicTransport(Transport):
    STOP_REASONS = {
        "end_turn": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "refusal": "content_filter",
    }

    def complete(self, route: Route, payload: dict[str, Any], timeout: float) -> dict:
        system, messages = self._messages(payload.get("messages", []))
        body: dict[str, Any] = {
            "model": route.model,
            "messages": messages,
            "max_tokens": _positive_int(payload.get("max_tokens"), 16384),
        }
        if system:
            body["system"] = system
        if payload.get("tools"):
            body["tools"] = [
                {
                    "name": tool["function"]["name"],
                    "description": tool["function"].get("description", ""),
                    "input_schema": tool["function"].get("parameters", {"type": "object"}),
                }
                for tool in payload["tools"]
            ]
        raw = self.request(
            f"{route.provider.base_url.rstrip('/')}/messages",
            body,
            _headers(route, bearer=False) | {"anthropic-version": "2023-06-01"},
            timeout,
        )
        return self._normalize(raw, route.model)

    @staticmethod
    def _messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        systems: list[str] = []
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role in {"system", "developer"}:
                systems.append(str(message.get("content", "")))
                continue
            if role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id", ""),
                            "content": str(message.get("content", "")),
                        }],
                    }
                )
                continue
            content: Any = message.get("content", "")
            if role == "assistant" and message.get("tool_calls"):
                blocks = [{"type": "text", "text": str(content)}] if content else []
                for call in message["tool_calls"]:
                    function = call.get("function", {})
                    try:
                        arguments = json.loads(function.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        arguments = {}
                    blocks.append({
                        "type": "tool_use", "id": call.get("id", str(uuid4())),
                        "name": function.get("name", ""), "input": arguments,
                    })
                content = blocks
            converted.append({"role": role, "content": content})
        return "\n\n".join(systems), converted

    def _normalize(self, raw: dict[str, Any], model: str) -> dict[str, Any]:
        text: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in raw.get("content", []):
            if block.get("type") == "text":
                text.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", str(uuid4())),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
        usage = raw.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens", 0))
        completion_tokens = int(usage.get("output_tokens", 0))
        return {
            "id": raw.get("id", f"agentos-{uuid4()}"),
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "\n".join(text) or None,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "finish_reason": self.STOP_REASONS.get(raw.get("stop_reason"), "stop"),
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


class GatewayClient:
    def __init__(self) -> None:
        self.transports: dict[str, Transport] = {
            "openai_chat": OpenAITransport(),
            "anthropic_messages": AnthropicTransport(),
        }

    def complete(self, route: Route, payload: dict[str, Any], timeout: float = 120) -> dict:
        if payload.get("stream"):
            raise ValueError("streaming is not yet supported by this gateway milestone")
        transport = self.transports.get(route.provider.transport)
        if not transport:
            raise GatewayUpstreamError(f"unsupported transport: {route.provider.transport}")
        result = transport.complete(route, payload, timeout)
        result["agentos_route"] = {"provider": route.provider.id, "model": route.model}
        return result


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "messages", "tools", "tool_choice", "temperature", "top_p", "max_tokens",
        "max_completion_tokens", "stop", "response_format", "seed", "user",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _headers(route: Route, bearer: bool) -> dict[str, str]:
    headers = {"content-type": "application/json", "user-agent": "AgentOS/0.2"}
    if route.provider.secret_env:
        value = os.environ[route.provider.secret_env]
        headers["authorization" if bearer else "x-api-key"] = (
            f"Bearer {value}" if bearer else value
        )
    return headers


def _positive_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
