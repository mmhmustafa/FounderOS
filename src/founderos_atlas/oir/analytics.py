"""Workflow analytics: RECORD-ONLY intent telemetry (PR-164 Part 10,
hardened by PR-164.1 Part 9).

Atlas records which intents were detected, at what confidence, and
which recommended workflow the operator actually opened. The records
are append-only JSON lines under the workspace output directory —
operator-readable, exportable, and deletable like any other artifact.

Hardening (PR-164.1):
- every record carries ``schema`` (ANALYTICS_SCHEMA_VERSION);
- input is validated and bounded — only JSON scalars, field names and
  values truncated, field count capped — so a hostile or buggy caller
  cannot bloat or corrupt the log;
- the file rotates at MAX_FILE_BYTES, keeping MAX_BACKUPS numbered
  backups (retention is bounded by construction);
- every failure is swallowed: analytics must NEVER impact routing or
  answering.

This data is for the OPERATOR's understanding of how Atlas is used.
It is never fed back into detection: routing stays the deterministic
catalog, and nothing here trains, weights, or adapts anything.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any


ANALYTICS_FILENAME = "oir-analytics.jsonl"
ANALYTICS_SCHEMA_VERSION = "1.1.0"

MAX_FILE_BYTES = 5 * 1024 * 1024   # rotate past this size
MAX_BACKUPS = 3                    # oir-analytics.jsonl.1 … .3
MAX_FIELD_CHARS = 300              # per string value (and per key)
MAX_FIELDS = 24                    # per record
MAX_KIND_CHARS = 40

# Provenance markers the recorder stamps itself; caller payload may
# never overwrite them (a forged "schema"/"kind" would defeat the very
# fields that make records trustworthy).
_RESERVED_KEYS = frozenset(("schema", "kind"))

# One writer at a time: rotation is a multi-step rename chain, and two
# threads interleaving it could clobber a backup or lose the append.
_write_lock = threading.Lock()


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Bound and validate one record's fields. Strings are truncated,
    non-scalar values dropped, reserved keys refused, field count
    capped — deterministic and silent, because analytics never gets
    to throw."""

    clean: dict[str, Any] = {}
    for name, value in payload.items():
        if len(clean) >= MAX_FIELDS:
            break
        key = str(name)[:MAX_FIELD_CHARS]
        if not key or key in _RESERVED_KEYS:
            continue
        if isinstance(value, bool) or value is None:
            clean[key] = value
        elif isinstance(value, int):
            clean[key] = value
        elif isinstance(value, float):
            # NaN/Infinity would make json.dumps emit tokens strict
            # JSON parsers reject; finite floats only.
            if math.isfinite(value):
                clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:MAX_FIELD_CHARS]
        # anything else (lists, dicts, objects) is dropped: records are
        # flat scalars by contract
    return clean


class IntentAnalytics:
    """Append-only, size-bounded intent telemetry for one workspace."""

    def __init__(self, base_dir: Path) -> None:
        self.path = Path(base_dir) / ANALYTICS_FILENAME

    # -- writing ---------------------------------------------------------

    def _rotate_if_needed(self) -> None:
        try:
            if (not self.path.is_file()
                    or self.path.stat().st_size < MAX_FILE_BYTES):
                return
            oldest = self.path.with_name(
                f"{self.path.name}.{MAX_BACKUPS}"
            )
            if oldest.exists():
                oldest.unlink()
            for index in range(MAX_BACKUPS - 1, 0, -1):
                source = self.path.with_name(f"{self.path.name}.{index}")
                if source.exists():
                    source.rename(
                        self.path.with_name(f"{self.path.name}.{index + 1}")
                    )
            self.path.rename(self.path.with_name(f"{self.path.name}.1"))
        except OSError:
            pass  # rotation is best-effort; the append below still tries

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        """Append one validated event. Best-effort: failures never
        propagate, and malformed input is bounded, never written raw."""

        event = _sanitize(payload)
        # Stamped LAST so no payload key can ever overwrite them.
        event["schema"] = ANALYTICS_SCHEMA_VERSION
        event["kind"] = str(kind)[:MAX_KIND_CHARS]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _write_lock:
                self._rotate_if_needed()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, sort_keys=True) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    # -- reading ---------------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        """Every recorded event in the CURRENT file, oldest first;
        unreadable lines skipped (tolerant by design)."""

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
