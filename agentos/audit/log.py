from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

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
                # fsync so the tamper-evident chain survives power loss.
                os.fsync(stream.fileno())
            self._last_hash = record["hash"]
            return record

    def query(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        actor_id: str = "",
        event_type: str = "",
        correlation_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return filtered audit records in chronological order.

        All filters are optional and combined with AND semantics.
        Pagination uses offset (number of matching records to skip) and limit.
        """
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)
        results: list[dict[str, Any]] = []
        if not self.path.exists():
            return results
        with self._lock:
            path_snapshot = self.path
        skipped = 0
        with path_snapshot.open(encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if actor_id and record.get("actor_id") != actor_id:
                    continue
                if event_type and record.get("event_type") != event_type:
                    continue
                if correlation_id and record.get("correlation_id") != correlation_id:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                results.append(record)
                if len(results) >= limit:
                    break
        return results
