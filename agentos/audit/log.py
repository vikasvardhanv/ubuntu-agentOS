from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from agentos.domain.models import AuditEvent


class AuditLog:
    """Append-only, hash-chained JSONL audit log."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = ""
        with self.path.open(encoding="utf-8") as stream:
            for last in stream:
                pass
        if not last:
            return "0" * 64
        try:
            return str(json.loads(last)["hash"])
        except (KeyError, ValueError, TypeError):
            raise RuntimeError(f"invalid audit chain at {self.path}") from None

    def append(self, event: AuditEvent) -> dict:
        with self._lock:
            record = event.as_dict()
            record["previous_hash"] = self._last_hash
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
            record["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
                stream.flush()
            self._last_hash = record["hash"]
            return record
