"""Workflow analytics: RECORD-ONLY intent telemetry (PR-164, Part 10).

Atlas records which intents were detected, at what confidence, and
which recommended workflow the operator actually opened. The records
are append-only JSON lines under the workspace output directory —
operator-readable, exportable, and deletable like any other artifact.

This data is for the OPERATOR's understanding of how Atlas is used.
It is never fed back into detection: routing stays the deterministic
catalog, and nothing here trains, weights, or adapts anything.
Recording is best-effort by design — a full disk or locked file must
never break answering — and failures are silently swallowed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ANALYTICS_FILENAME = "oir-analytics.jsonl"


class IntentAnalytics:
    """Append-only intent telemetry for one workspace."""

    def __init__(self, base_dir: Path) -> None:
        self.path = Path(base_dir) / ANALYTICS_FILENAME

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        """Append one event. Best-effort: failures never propagate."""

        event = {"kind": str(kind)}
        event.update(payload)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    def entries(self) -> list[dict[str, Any]]:
        """Every recorded event, oldest first; unreadable lines skipped."""

        if not self.path.is_file():
            return []
        events: list[dict[str, Any]] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events
