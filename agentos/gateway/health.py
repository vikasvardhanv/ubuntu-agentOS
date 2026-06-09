from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class Circuit:
    failures: int = 0
    opened_at: float = 0


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown: float = 30):
        self.threshold = threshold
        self.cooldown = cooldown
        self._circuits: dict[str, Circuit] = {}
        self._lock = threading.Lock()

    def available(self, provider_id: str) -> bool:
        with self._lock:
            circuit = self._circuits.get(provider_id)
            if not circuit or circuit.failures < self.threshold:
                return True
            if time.monotonic() - circuit.opened_at >= self.cooldown:
                circuit.failures = 0
                return True
            return False

    def success(self, provider_id: str) -> None:
        with self._lock:
            self._circuits.pop(provider_id, None)

    def failure(self, provider_id: str) -> None:
        with self._lock:
            circuit = self._circuits.setdefault(provider_id, Circuit())
            circuit.failures += 1
            if circuit.failures >= self.threshold:
                circuit.opened_at = time.monotonic()

    def status(self) -> dict[str, dict[str, int | bool]]:
        with self._lock:
            return {
                key: {"failures": value.failures, "open": value.failures >= self.threshold}
                for key, value in self._circuits.items()
            }
