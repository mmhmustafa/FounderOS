"""Compliance trend: the score over time, recorded when it changes.

A trend point is appended when the recorded counts differ from the last
point for the scope — viewing the page never spams the file, and the
series stays meaningful (each point is a real change in posture).
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from founderos_atlas.workspace.repository import default_workspace_root


POLICY_TREND_FILENAME = "policy-trend.json"
MAX_POINTS_PER_SCOPE = 60


class PolicyTrend:
    _locks: dict[str, RLock] = {}
    _locks_guard = RLock()

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = (
            Path(workspace_root) if workspace_root is not None
            else default_workspace_root()
        )
        resolved = str(self._root.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(resolved, RLock())

    @property
    def path(self) -> Path:
        return self._root / POLICY_TREND_FILENAME

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.is_file():
            return {}
        try:
            return dict(
                json.loads(self.path.read_text(encoding="utf-8")).get(
                    "scopes"
                ) or {}
            )
        except (OSError, ValueError, json.JSONDecodeError):
            # A corrupt trend never blocks the policy page; it restarts.
            return {}

    def series(self, scope_id: str) -> list[dict[str, Any]]:
        return list(self._load().get(scope_id) or [])

    def record(
        self,
        *,
        scope_id: str,
        recorded_at: str,
        score: int,
        passed: int,
        failed: int,
        warnings: int,
        unknown: int,
    ) -> bool:
        """Append a point if posture changed; returns whether it recorded."""

        point = {
            "recorded_at": recorded_at, "score": int(score),
            "passed": int(passed), "failed": int(failed),
            "warnings": int(warnings), "unknown": int(unknown),
        }
        with self._lock:
            data = self._load()
            series = data.setdefault(scope_id, [])
            if series:
                last = {k: v for k, v in series[-1].items()
                        if k != "recorded_at"}
                if last == {k: v for k, v in point.items()
                            if k != "recorded_at"}:
                    return False
            series.append(point)
            del series[:-MAX_POINTS_PER_SCOPE]
            self._root.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(
                f".{self.path.name}.{uuid4().hex}.writing"
            )
            try:
                temporary.write_text(
                    json.dumps({"scopes": data}, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        return True
