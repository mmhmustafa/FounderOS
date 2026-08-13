"""Unified, filterable change exploration across the three change kinds.

Topology, configuration, and operational change reports each keep their
own detector and schema; this module folds their entries into ONE row
shape for investigation — kind, category, severity, device, field,
before/after, description, recommendation — plus deterministic subject
fingerprints so acknowledgements, assignments, notes, and suppressions
(audit/annotations.py) survive re-renders and re-discoveries of the
same change.

PR-178.2A: identity is SCOPED. A change is an observation made by one
observation point, so the canonical subject is
``change:v2:<scope_id>:<content-hash>`` (change/identity.py) — the
identical delta reported by two profiles is two annotatable changes,
and an action in one scope can never mutate another's record. Rows also
carry ``subject_legacy`` (the pre-isolation content-only id) so reads
can fall back to legacy annotations without ever writing through them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .identity import resolve_annotation, subject_v1, subject_v2


CHANGE_KINDS = ("topology", "configuration", "operational")


def change_fingerprint(row: Mapping[str, Any]) -> str:
    """The LEGACY (v1) identity: content only, scope-blind.

    Kept for compatibility and for the v3 migration's classification;
    new rows carry the scoped v2 subject as their canonical identity.
    """

    return subject_v1(row)


def unified_rows(
    *,
    topology_report: Mapping[str, Any] | None,
    config_report: Mapping[str, Any] | None,
    state_report: Mapping[str, Any] | None,
    scope_id: str,
    network: str = "",
    incident_devices: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Every change of a scope as one investigation row shape.

    ``scope_id`` is the STABLE scope identifier (profile_id or
    "default") and is required: identity needs its observation point.
    ``network`` remains the display label and is deliberately NOT part
    of identity — it changes on rename; the id does not.
    """

    rows: list[dict[str, Any]] = []

    def finish(row: dict[str, Any]) -> None:
        row["network"] = network
        row["subject"] = subject_v2(row, scope_id)
        row["subject_legacy"] = subject_v1(row)
        row["scope_id"] = scope_id
        row["incident_correlated"] = (
            str(row.get("device") or "").casefold()
            in {name.casefold() for name in incident_devices}
        )
        rows.append(row)

    for change in (topology_report or {}).get("changes") or ():
        finish({
            "kind": "topology",
            "category": str(change.get("category") or "topology"),
            "severity": str(change.get("severity") or "info"),
            "device": str(change.get("subject") or ""),
            "field": str(change.get("field") or ""),
            "before": _plain(change.get("previous_value")),
            "after": _plain(change.get("current_value")),
            "description": str(change.get("description") or ""),
            "recommendation": str(change.get("recommendation") or ""),
            "occurred_at": str(
                (topology_report or {}).get("generated_at") or ""
            ),
            "confidence": None,
        })
    for change in (config_report or {}).get("changes") or ():
        finish({
            "kind": "configuration",
            "category": str(change.get("category") or "configuration"),
            "severity": str(change.get("severity") or "info"),
            "device": str(change.get("hostname") or ""),
            "field": str(change.get("category") or ""),
            "before": _plain(change.get("previous_value")),
            "after": _plain(change.get("current_value")),
            "description": str(
                change.get("summary") or change.get("description") or ""
            ),
            "recommendation": str(change.get("recommendation") or ""),
            "occurred_at": str((config_report or {}).get("generated_at") or ""),
            "confidence": None,
        })
    for change in (state_report or {}).get("changes") or ():
        finish({
            "kind": "operational",
            "category": str(
                change.get("change_type") or change.get("event")
                or "operational"
            ),
            "severity": str(change.get("severity") or "info"),
            "device": str(change.get("hostname") or ""),
            "field": " ".join(filter(None, (
                str(change.get("interface") or ""),
                str(change.get("field") or ""),
            ))),
            "before": _plain(change.get("previous_value")),
            "after": _plain(change.get("current_value")),
            "description": str(change.get("description") or ""),
            "recommendation": str(change.get("recommendation") or ""),
            "occurred_at": str((state_report or {}).get("generated_at") or ""),
            "confidence": None,
        })
    return rows


def _plain(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def annotate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    acks: Mapping[str, Mapping[str, Any]] | None = None,
    assignments: Mapping[str, Mapping[str, Any]] | None = None,
    notes: Mapping[str, Mapping[str, Any]] | None = None,
    suppressions: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Attach operator state to rows via the canonical v2→v1 resolver.

    PR-178.2A value semantics: a record's PRESENCE used to mean
    acknowledged/suppressed. A scoped record can now carry an explicit
    negative ({"acknowledged": False} / {"suppressed": False}) — written
    when an operator un-acknowledges or un-suppresses a row whose state
    came from a READ-ONLY legacy record. The scoped negative wins in its
    scope; the legacy record keeps serving every other scope untouched.
    Records without the key (all legacy and all normal positive writes)
    keep meaning what they always did.
    """

    acks = dict(acks or {})
    assignments = dict(assignments or {})
    notes = dict(notes or {})
    suppressions = dict(suppressions or {})
    out: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        subject = str(entry.get("subject"))
        legacy = str(entry.get("subject_legacy") or "")
        ack = resolve_annotation(acks, subject, legacy)
        entry["acknowledged"] = (
            ack is not None and ack.get("acknowledged", True) is not False
        )
        entry["owner"] = str(
            (resolve_annotation(assignments, subject, legacy) or {})
            .get("owner") or ""
        )
        entry["note"] = str(
            (resolve_annotation(notes, subject, legacy) or {}).get("note") or ""
        )
        suppression = resolve_annotation(suppressions, subject, legacy)
        entry["suppressed"] = (
            suppression is not None
            and suppression.get("suppressed", True) is not False
        )
        entry["suppression_reason"] = str(
            (suppression or {}).get("reason") or ""
        ) if entry["suppressed"] else ""
        out.append(entry)
    return out


@dataclass(frozen=True)
class ChangeFilter:
    query: str = ""
    kind: str = ""
    category: str = ""
    severity: str = ""
    device: str = ""
    status: str = ""                # "", acknowledged, unacknowledged
    show_suppressed: bool = False
    # PR-178.2: one bulk operation's correlation id. The route resolves
    # it to the batch's subjects from the AUDIT log (durable for both
    # set- and clear-type actions) — never a subject list in a URL.
    batch: str = ""
    page: int = 1
    per_page: int = 50

    @classmethod
    def from_args(cls, args: Mapping[str, str]) -> "ChangeFilter":
        from founderos_atlas.listing import DEFAULT_PER_PAGE, MAX_PER_PAGE, int_arg

        return cls(
            query=str(args.get("q", "") or "").strip(),
            kind=str(args.get("kind", "") or "").strip(),
            category=str(args.get("category", "") or "").strip(),
            severity=str(args.get("severity", "") or "").strip(),
            device=str(args.get("device", "") or "").strip(),
            status=str(args.get("status", "") or "").strip(),
            show_suppressed=str(args.get("suppressed", "")) == "1",
            batch=str(args.get("batch", "") or "").strip(),
            page=int_arg(args, "page", 1, 100000),
            per_page=int_arg(args, "per_page", DEFAULT_PER_PAGE, MAX_PER_PAGE),
        )

    def to_args(self) -> dict[str, str]:
        pairs = {
            "q": self.query, "kind": self.kind, "category": self.category,
            "severity": self.severity, "device": self.device,
            "status": self.status,
            "suppressed": "1" if self.show_suppressed else "",
            "batch": self.batch,
        }
        return {key: value for key, value in pairs.items() if value}


_SEVERITY_ORDER = {"high": 0, "critical": 0, "medium": 1, "low": 2, "info": 3}


def filter_rows(
    rows: Sequence[Mapping[str, Any]],
    filters: ChangeFilter,
    *,
    batch_subjects: frozenset[str] | set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """(matching rows, suppressed-and-hidden count).

    ``batch_subjects`` is the resolved subject set of ``filters.batch``.
    A batch view shows exactly the batch's rows — including suppressed
    ones, because a suppression batch IS suppressed rows; hiding them
    would make the review page show nothing.
    """

    found: list[dict[str, Any]] = []
    hidden = 0
    needle = filters.query.casefold()
    show_suppressed = filters.show_suppressed or bool(filters.batch)
    for row in rows:
        if filters.batch:
            if str(row.get("subject")) not in (batch_subjects or ()):
                continue
        if row.get("suppressed") and not show_suppressed:
            hidden += 1
            continue
        if filters.kind and str(row.get("kind")) != filters.kind:
            continue
        if filters.category and str(row.get("category")) != filters.category:
            continue
        if filters.severity and str(row.get("severity")) != filters.severity:
            continue
        if filters.device and (
            str(row.get("device") or "").casefold()
            != filters.device.casefold()
        ):
            continue
        if filters.status == "acknowledged" and not row.get("acknowledged"):
            continue
        if filters.status == "unacknowledged" and row.get("acknowledged"):
            continue
        if needle:
            haystack = " ".join((
                str(row.get("device") or ""),
                str(row.get("description") or ""),
                str(row.get("category") or ""),
                str(row.get("field") or ""),
                str(row.get("before") or ""),
                str(row.get("after") or ""),
            )).casefold()
            if needle not in haystack:
                continue
        found.append(dict(row))
    found.sort(key=lambda row: (
        _SEVERITY_ORDER.get(str(row.get("severity")), 9),
        str(row.get("kind")),
        str(row.get("device") or "").casefold(),
        str(row.get("description") or ""),
    ))
    return found, hidden


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {
        "total": len(rows), "topology": 0, "configuration": 0,
        "operational": 0, "high": 0, "medium": 0, "low": 0,
        "acknowledged": 0, "suppressed": 0, "incident_correlated": 0,
    }
    for row in rows:
        counts[str(row.get("kind"))] = counts.get(str(row.get("kind")), 0) + 1
        severity = str(row.get("severity"))
        if severity in counts:
            counts[severity] += 1
        if row.get("acknowledged"):
            counts["acknowledged"] += 1
        if row.get("suppressed"):
            counts["suppressed"] += 1
        if row.get("incident_correlated"):
            counts["incident_correlated"] += 1
    return counts


def export_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "kind": str(row.get("kind") or ""),
            "category": str(row.get("category") or ""),
            "severity": str(row.get("severity") or ""),
            "device": str(row.get("device") or ""),
            "field": str(row.get("field") or ""),
            "before": str(row.get("before") or ""),
            "after": str(row.get("after") or ""),
            "description": str(row.get("description") or ""),
            "recommendation": str(row.get("recommendation") or ""),
            "network": str(row.get("network") or ""),
            "occurred_at": str(row.get("occurred_at") or ""),
            "acknowledged": "yes" if row.get("acknowledged") else "no",
            "owner": str(row.get("owner") or ""),
            "suppressed": "yes" if row.get("suppressed") else "no",
            "subject": str(row.get("subject") or ""),
        }
        for row in rows
    ]
