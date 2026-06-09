from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureKind(StrEnum):
    AUTH = "auth"
    BILLING = "billing"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVER = "server"
    MODEL = "model"
    POLICY = "policy"
    REQUEST = "request"
    UNKNOWN = "unknown"


@dataclass
class GatewayUpstreamError(RuntimeError):
    message: str
    kind: FailureKind = FailureKind.UNKNOWN
    status: int | None = None
    retryable: bool = False
    fallback: bool = True

    def __str__(self) -> str:
        return self.message


def classify(status: int | None, message: str) -> GatewayUpstreamError:
    text = message.lower()
    if status in {401, 403}:
        return GatewayUpstreamError(message, FailureKind.AUTH, status, False, True)
    if status == 402 or any(value in text for value in ("insufficient quota", "payment required")):
        return GatewayUpstreamError(message, FailureKind.BILLING, status, False, True)
    if status == 429 or "rate limit" in text:
        return GatewayUpstreamError(message, FailureKind.RATE_LIMIT, status, True, True)
    if status in {500, 502, 503, 504, 529}:
        return GatewayUpstreamError(message, FailureKind.SERVER, status, True, True)
    if status == 404 or "model not found" in text:
        return GatewayUpstreamError(message, FailureKind.MODEL, status, False, True)
    if "data policy" in text or "guardrail restriction" in text:
        return GatewayUpstreamError(message, FailureKind.POLICY, status, False, True)
    if status is not None and 400 <= status < 500:
        return GatewayUpstreamError(message, FailureKind.REQUEST, status, False, False)
    return GatewayUpstreamError(message, FailureKind.UNKNOWN, status, True, True)
