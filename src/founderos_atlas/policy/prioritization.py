"""Operational prioritization and regression history for policy results."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


POLICY_POSTURE_FILENAME = "policy-posture.json"
POLICY_POSTURE_SCHEMA_VERSION = "1.0.0"

_SEVERITY = {
    "critical": 50,
    "high": 35,
    "medium": 20,
    "low": 8,
    "info": 2,
    "informational": 2,
}
_INTENT = {"required": 20, "recommended": 8, "informational": 0}
_CRITICAL_ROLES = {"firewall", "router", "layer3_switch", "load_balancer"}
_CRITICAL_SITE_TYPES = {"datacenter", "wan", "internet", "cloud"}


def priority_score(row: Mapping[str, Any], *, blast_radius: int = 1) -> int:
    """Deterministic risk score; stale/missing evidence can never outrank a
    fresh confirmed failure of otherwise equal severity."""

    status = str(row.get("effective_status") or "")
    if status not in ("fail", "warning"):
        return 0
    policy = row.get("policy") or {}
    context = row.get("device_context") or {}
    score = _SEVERITY.get(str(policy.get("severity") or "").casefold(), 0)
    score += _INTENT.get(str(row.get("intent") or "required"), 0)
    score += min(20, max(0, int(blast_radius) - 1))
    if str(context.get("role") or "") in _CRITICAL_ROLES:
        score += 8
    if str(context.get("site_type") or "") in _CRITICAL_SITE_TYPES:
        score += 6
    if row.get("is_new_regression"):
        score += 20
    freshness = row.get("evidence_fresh")
    if freshness is False:
        score -= 25
    elif freshness is None:
        score -= 12
    try:
        confidence = float(
            ((row.get("result") or {}).get("confidence") or {}).get("score")
            or 0
        )
    except (TypeError, ValueError):
        confidence = 0
    if confidence >= 0.85:
        score += 8
    elif confidence < 0.5:
        score -= 8
    return max(0, score)


def prioritize(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Enrich rows with blast radius, risk score and a human explanation."""

    failure_counts = Counter(
        str((row.get("policy") or {}).get("policy_id") or "")
        for row in rows
        if str(row.get("effective_status") or "") in ("fail", "warning")
    )
    enriched: list[dict[str, Any]] = []
    for value in rows:
        row = dict(value)
        policy_id = str((row.get("policy") or {}).get("policy_id") or "")
        blast = failure_counts.get(policy_id, 0)
        row["blast_radius"] = blast
        row["priority_score"] = priority_score(row, blast_radius=blast)
        if row.get("effective_status") in ("fail", "warning"):
            facts = [
                str((row.get("policy") or {}).get("severity") or "unknown")
                + " severity",
                str(row.get("intent") or "required") + " intent",
                f"{blast} affected device(s)",
            ]
            if row.get("is_new_regression"):
                facts.append("new regression")
            if row.get("evidence_fresh") is False:
                facts.append("stale evidence; verify before action")
            elif row.get("evidence_fresh") is None:
                facts.append("evidence age unknown")
            row["priority_explanation"] = "; ".join(facts)
        else:
            row["priority_explanation"] = ""
        enriched.append(row)
    return enriched


def priority_summary(
    rows: Sequence[Mapping[str, Any]], *, limit: int = 5
) -> dict[str, Any]:
    actionable = [
        dict(row)
        for row in rows
        if row.get("effective_status") in ("fail", "warning")
    ]
    actionable.sort(key=lambda row: (
        -int(row.get("priority_score") or 0),
        str((row.get("policy") or {}).get("name") or "").casefold(),
        str(row.get("hostname") or "").casefold(),
    ))
    themes: dict[str, dict[str, Any]] = {}
    for row in actionable:
        policy = row.get("policy") or {}
        policy_id = str(policy.get("policy_id") or "")
        entry = themes.setdefault(policy_id, {
            "policy_id": policy_id,
            "name": str(policy.get("name") or ""),
            "severity": str(policy.get("severity") or ""),
            "intent": str(row.get("intent") or "required"),
            "count": 0,
            "confirmed": 0,
            "new_regressions": 0,
            "max_priority": 0,
        })
        entry["count"] += 1
        entry["confirmed"] += int(row.get("verdict_quality") == "confirmed")
        entry["new_regressions"] += int(bool(row.get("is_new_regression")))
        entry["max_priority"] = max(
            entry["max_priority"], int(row.get("priority_score") or 0)
        )
    ordered_themes = sorted(
        themes.values(),
        key=lambda item: (
            -item["new_regressions"],
            -item["max_priority"],
            -item["count"],
            item["name"].casefold(),
        ),
    )
    return {
        "new_regressions": sum(
            1 for row in actionable if row.get("is_new_regression")
        ),
        "confirmed_failures": sum(
            1 for row in actionable if row.get("verdict_quality") == "confirmed"
        ),
        "stale_or_unverified": sum(
            1 for row in actionable if row.get("verdict_quality") != "confirmed"
        ),
        "top_results": actionable[:limit],
        "top_themes": ordered_themes[:limit],
    }


class PolicyPostureHistory:
    """One last-known status snapshot per scope.

    The store records only result subjects and dispositions, never
    configuration or evidence content.
    """

    _locks: dict[str, RLock] = {}
    _locks_guard = RLock()

    def __init__(self, workspace_root: str | Path) -> None:
        self.path = Path(workspace_root) / POLICY_POSTURE_FILENAME
        with self._locks_guard:
            self._lock = self._locks.setdefault(
                str(self.path.resolve()), RLock()
            )

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": POLICY_POSTURE_SCHEMA_VERSION,
                "scopes": {},
            }
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(value) if isinstance(value, Mapping) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                "schema_version": POLICY_POSTURE_SCHEMA_VERSION,
                "scopes": {},
            }

    def compare_and_record(
        self,
        *,
        scope_id: str,
        source_revision: str,
        rows: Sequence[Mapping[str, Any]],
        recorded_at: str,
    ) -> frozenset[str]:
        current = {
            str(row.get("subject") or ""): str(
                row.get("effective_status") or "unknown"
            )
            for row in rows
            if row.get("subject")
        }
        with self._lock:
            document = self._read()
            scopes = dict(document.get("scopes") or {})
            previous = dict(scopes.get(scope_id) or {})
            if str(previous.get("source_revision") or "") == source_revision:
                return frozenset(
                    str(item) for item in previous.get("regressions") or ()
                )
            previous_statuses = dict(previous.get("statuses") or {})
            regressions = frozenset(
                subject
                for subject, status in current.items()
                if status == "fail"
                and previous_statuses
                and previous_statuses.get(subject) not in ("fail", "warning")
            )
            scopes[scope_id] = {
                "source_revision": source_revision,
                "recorded_at": recorded_at,
                "statuses": current,
                "regressions": sorted(regressions),
            }
            document = {
                "schema_version": POLICY_POSTURE_SCHEMA_VERSION,
                "scopes": scopes,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(
                f".{self.path.name}.{uuid4().hex}.writing"
            )
            try:
                temporary.write_text(
                    json.dumps(
                        document, indent=2, sort_keys=True, ensure_ascii=False
                    )
                    + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return regressions
