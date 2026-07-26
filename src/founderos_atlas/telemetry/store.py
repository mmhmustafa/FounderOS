"""Bounded, deduplicated telemetry persistence with simple downsampling."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .models import TelemetryFact

TELEMETRY_FILENAME = "telemetry.jsonl"
DEFAULT_MAX_FACTS = 100_000
_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


class TelemetryStore:
    def __init__(
        self,
        workspace_root: str | Path,
        *,
        max_facts: int = DEFAULT_MAX_FACTS,
        retention_days: int = 30,
    ) -> None:
        if max_facts < 1 or retention_days < 1:
            raise ValueError("telemetry bounds must be positive")
        self.path = Path(workspace_root) / TELEMETRY_FILENAME
        self.max_facts = int(max_facts)
        self.retention_days = int(retention_days)
        resolved = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(resolved, RLock())

    def _read(self) -> list[TelemetryFact]:
        if not self.path.is_file():
            return []
        facts: list[TelemetryFact] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                facts.append(TelemetryFact.from_dict(json.loads(line)))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        return facts

    def _write(self, facts: list[TelemetryFact]) -> None:
        facts.sort(key=lambda item: (item.observed_at, item.fact_id))
        facts = facts[-self.max_facts:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                "".join(
                    json.dumps(item.to_dict(), sort_keys=True) + "\n"
                    for item in facts
                ),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def ingest(self, facts) -> int:
        incoming = list(facts)
        if not all(isinstance(item, TelemetryFact) for item in incoming):
            raise TypeError("telemetry ingest accepts TelemetryFact values")
        with self._lock:
            existing = self._read()
            known = {item.fact_id for item in existing}
            added = [item for item in incoming if item.fact_id not in known]
            self._write([*existing, *added])
        return len(added)

    def query(
        self,
        *,
        scope_id: str | None = None,
        entity_id: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[TelemetryFact]:
        facts = self._read()
        if scope_id:
            facts = [item for item in facts if item.scope_id == scope_id]
        if entity_id:
            facts = [item for item in facts if item.entity_id == entity_id]
        if kind:
            facts = [item for item in facts if item.kind == kind]
        if since:
            if since.tzinfo is None:
                raise ValueError("telemetry query time must include a timezone")
            threshold = since.astimezone(timezone.utc)
            facts = [
                item for item in facts
                if datetime.fromisoformat(item.observed_at).astimezone(
                    timezone.utc
                ) >= threshold
            ]
        facts.sort(key=lambda item: item.observed_at, reverse=True)
        return facts[:max(1, min(int(limit), self.max_facts))]

    def prune(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("telemetry prune time must include a timezone")
        threshold = now.astimezone(timezone.utc) - timedelta(
            days=self.retention_days
        )
        with self._lock:
            facts = self._read()
            kept = [
                item for item in facts
                if datetime.fromisoformat(item.observed_at).astimezone(
                    timezone.utc
                ) >= threshold
            ]
            self._write(kept)
        return len(facts) - len(kept)

    def downsample(
        self,
        *,
        kind: str,
        bucket_minutes: int = 60,
        scope_id: str | None = None,
    ) -> list[dict]:
        if bucket_minutes < 1:
            raise ValueError("bucket_minutes must be positive")
        grouped: dict[tuple, list[float]] = defaultdict(list)
        for item in self.query(
            kind=kind, scope_id=scope_id, limit=10_000
        ):
            if not isinstance(item.value, (int, float)) or isinstance(
                item.value, bool
            ):
                continue
            moment = datetime.fromisoformat(item.observed_at)
            seconds = max(60, int(bucket_minutes) * 60)
            bucket = datetime.fromtimestamp(
                int(moment.timestamp()) // seconds * seconds,
                tz=moment.tzinfo,
            )
            grouped[(item.entity_id, bucket.isoformat())].append(
                float(item.value)
            )
        return [
            {
                "entity_id": entity,
                "bucket": bucket,
                "minimum": min(values),
                "maximum": max(values),
                "average": sum(values) / len(values),
                "samples": len(values),
            }
            for (entity, bucket), values in sorted(grouped.items())
        ]
