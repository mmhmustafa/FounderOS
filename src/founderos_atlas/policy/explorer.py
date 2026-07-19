"""Scalable, filterable policy-result exploration.

The engine's report stays authoritative; this module derives the
investigation view over it: effective status buckets (pass / warning /
fail / unknown / missing-evidence / not-applicable / excepted),
filtering, grouping, pagination, summaries, a compact heatmap, and
export rows. Everything is a pure function over the report dict plus
the exception catalog, so scale behavior is testable without a browser.

Status semantics
----------------
``unknown`` and ``missing evidence`` are deliberately separate: both
come from the engine's Unknown conclusion, but a verdict with recorded
evidence GAPS is answerable by collecting (missing evidence), while an
Unknown without gaps means the evidence existed and was inconclusive.
``not applicable`` is a pass whose checks state the policy's antecedent
is absent — never counted as compliance earned. ``excepted`` is a fail
or warning covered by an active, audited exception.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


EFFECTIVE_STATUSES = (
    "fail", "warning", "missing-evidence", "unknown",
    "not-applicable", "excepted", "pass",
)

STATUS_LABELS = {
    "fail": "Failed",
    "warning": "Warning",
    "missing-evidence": "Missing evidence",
    "unknown": "Unknown",
    "not-applicable": "Not applicable",
    "excepted": "Excepted",
    "pass": "Passed",
}

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


def effective_status(
    evaluation: Mapping[str, Any], *, excepted: bool = False
) -> str:
    """The investigation bucket for one engine evaluation."""

    status = str(evaluation.get("status") or "unknown")
    if excepted and status in ("fail", "warning"):
        return "excepted"
    if status == "unknown":
        gaps = (evaluation.get("result") or {}).get("evidence_missing") or ()
        return "missing-evidence" if gaps else "unknown"
    if status == "pass":
        result = evaluation.get("result") or {}
        statements = " ".join(
            str(step.get("statement") or "")
            for step in result.get("reasoning_path") or ()
        )
        if "not applicable" in statements.casefold():
            return "not-applicable"
    return status


def evidence_is_fresh(
    evaluation: Mapping[str, Any], now: str, *, window_hours: int = 24
) -> bool | None:
    """Freshness of the newest evidence behind a verdict; None = unknown."""

    from datetime import datetime

    newest: str | None = None
    for item in (evaluation.get("result") or {}).get("evidence_used") or ():
        observed = str(item.get("observed_at") or "")
        if observed and (newest is None or observed > newest):
            newest = observed
    if newest is None:
        return None
    try:
        age = (
            datetime.fromisoformat(now) - datetime.fromisoformat(newest)
        ).total_seconds()
    except ValueError:
        return None
    return age <= window_hours * 3600


@dataclass(frozen=True)
class ResultFilter:
    """One shareable filter state — every field round-trips via the URL."""

    query: str = ""
    status: str = ""
    severity: str = ""
    policy_id: str = ""
    site: str = ""
    device: str = ""
    platform: str = ""
    freshness: str = ""              # "", "fresh", "stale"
    group_by: str = ""               # "", policy, device, site, severity
    owner: str = ""                  # explicit owner filter
    assigned_to_me: bool = False     # "mine=1" — resolved server-side to
                                     # the authenticated principal; the
                                     # URL carries only the flag, never a
                                     # client-supplied identity
    assignment: str = ""             # assignment-batch correlation id
    page: int = 1
    per_page: int = DEFAULT_PER_PAGE

    @classmethod
    def from_args(cls, args: Mapping[str, str]) -> "ResultFilter":
        def _int(name: str, default: int, maximum: int) -> int:
            try:
                value = int(str(args.get(name, "") or default))
            except ValueError:
                value = default
            return max(1, min(value, maximum))

        return cls(
            query=str(args.get("q", "") or "").strip(),
            status=str(args.get("status", "") or "").strip(),
            severity=str(args.get("severity", "") or "").strip(),
            policy_id=str(args.get("policy", "") or "").strip(),
            site=str(args.get("site", "") or "").strip(),
            device=str(args.get("device", "") or "").strip(),
            platform=str(args.get("platform", "") or "").strip(),
            freshness=str(args.get("freshness", "") or "").strip(),
            group_by=str(args.get("group", "") or "").strip(),
            owner=str(args.get("owner", "") or "").strip(),
            assigned_to_me=str(args.get("mine", "") or "") == "1",
            assignment=str(args.get("assignment", "") or "").strip(),
            page=_int("page", 1, 100000),
            per_page=_int("per_page", DEFAULT_PER_PAGE, MAX_PER_PAGE),
        )

    def to_args(self) -> dict[str, str]:
        pairs = {
            "q": self.query, "status": self.status,
            "severity": self.severity, "policy": self.policy_id,
            "site": self.site, "device": self.device,
            "platform": self.platform, "freshness": self.freshness,
            "group": self.group_by, "owner": self.owner,
            "mine": "1" if self.assigned_to_me else "",
            "assignment": self.assignment,
        }
        return {key: value for key, value in pairs.items() if value}


def annotate_evaluations(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    now: str,
    exception_subjects: frozenset[str] = frozenset(),
    sites_by_device: Mapping[str, str] | None = None,
    platforms_by_device: Mapping[str, str] | None = None,
    owners_by_subject: Mapping[str, str] | None = None,
    assignments_by_subject: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Each evaluation extended with its investigation fields.

    ``assignments_by_subject`` carries the authoritative assignment
    annotation per subject (owner, batch correlation, assigner, stamp)
    so batch membership filters straight off the audited records.
    """

    sites = {k.casefold(): v for k, v in (sites_by_device or {}).items()}
    platforms = {
        k.casefold(): v for k, v in (platforms_by_device or {}).items()
    }
    owners = dict(owners_by_subject or {})
    assignments = dict(assignments_by_subject or {})
    rows: list[dict[str, Any]] = []
    for evaluation in evaluations:
        row = dict(evaluation)
        hostname = str(row.get("hostname") or "")
        policy = row.get("policy") or {}
        subject = result_subject(
            str(policy.get("policy_id") or ""), hostname
        )
        excepted = subject in exception_subjects
        fresh = evidence_is_fresh(row, now)
        row["subject"] = subject
        row["effective_status"] = effective_status(row, excepted=excepted)
        row["site"] = sites.get(hostname.casefold(), "unknown")
        row["platform"] = platforms.get(hostname.casefold(), "unknown")
        row["evidence_fresh"] = fresh
        row["owner"] = owners.get(subject, "")
        assignment = assignments.get(subject) or {}
        row["assignment_correlation"] = str(
            assignment.get("correlation") or ""
        )
        row["assigned_by"] = str(assignment.get("updated_by") or "")
        row["assigned_at"] = str(assignment.get("updated_at") or "")
        rows.append(row)
    return rows


def result_subject(policy_id: str, hostname: str) -> str:
    """The durable subject key of one policy×device result."""

    return f"policy-result:{policy_id}:{hostname.casefold()}"


def filter_rows(
    rows: Sequence[Mapping[str, Any]], filters: ResultFilter
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    needle = filters.query.casefold()
    for row in rows:
        policy = row.get("policy") or {}
        if filters.status and row.get("effective_status") != filters.status:
            continue
        if filters.severity and str(policy.get("severity")) != filters.severity:
            continue
        if filters.policy_id and str(policy.get("policy_id")) != filters.policy_id:
            continue
        if filters.site and str(row.get("site")) != filters.site:
            continue
        if filters.device and (
            str(row.get("hostname") or "").casefold()
            != filters.device.casefold()
        ):
            continue
        if filters.platform and str(row.get("platform")) != filters.platform:
            continue
        if filters.freshness == "fresh" and row.get("evidence_fresh") is not True:
            continue
        if filters.freshness == "stale" and row.get("evidence_fresh") is not False:
            continue
        if filters.owner and (
            str(row.get("owner") or "").casefold()
            != filters.owner.casefold()
        ):
            continue
        if filters.assignment and (
            str(row.get("assignment_correlation") or "") != filters.assignment
        ):
            continue
        if needle:
            haystack = " ".join((
                str(row.get("hostname") or ""),
                str(policy.get("name") or ""),
                str(policy.get("policy_id") or ""),
                str(policy.get("category") or ""),
                str((row.get("result") or {}).get("conclusion") or ""),
            )).casefold()
            if needle not in haystack:
                continue
        found.append(dict(row))
    return found


_STATUS_ORDER = {status: index for index, status in enumerate(EFFECTIVE_STATUSES)}


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic: severity of the problem first, then policy, then device."""

    return sorted(rows, key=lambda row: (
        _STATUS_ORDER.get(str(row.get("effective_status")), 99),
        str((row.get("policy") or {}).get("name") or ""),
        str(row.get("hostname") or "").casefold(),
    ))


def group_rows(
    rows: Sequence[Mapping[str, Any]], group_by: str
) -> list[dict[str, Any]]:
    """Ordered groups with per-status counts (bodies stay paginated)."""

    def key_of(row: Mapping[str, Any]) -> tuple[str, str]:
        policy = row.get("policy") or {}
        if group_by == "policy":
            return str(policy.get("policy_id")), str(policy.get("name"))
        if group_by == "device":
            hostname = str(row.get("hostname") or "unknown")
            return hostname.casefold(), hostname
        if group_by == "site":
            site = str(row.get("site") or "unknown")
            return site, site
        if group_by == "severity":
            severity = str(policy.get("severity") or "unknown")
            return severity, severity
        return "", ""

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key, label = key_of(row)
        entry = groups.setdefault(key, {
            "key": key, "label": label, "total": 0,
            "counts": {status: 0 for status in EFFECTIVE_STATUSES},
        })
        entry["total"] += 1
        entry["counts"][str(row.get("effective_status"))] = (
            entry["counts"].get(str(row.get("effective_status")), 0) + 1
        )
    ordered = sorted(
        groups.values(),
        key=lambda entry: (-entry["counts"]["fail"], entry["label"].casefold()),
    )
    return ordered


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    page: int
    pages: int
    per_page: int

    @property
    def start(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def end(self) -> int:
        return min(self.page * self.per_page, self.total)


def paginate(items: Sequence, page: int, per_page: int) -> Page:
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return Page(
        items=list(items[start:start + per_page]),
        total=total, page=page, pages=pages, per_page=per_page,
    )


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in EFFECTIVE_STATUSES}
    for row in rows:
        counts[str(row.get("effective_status"))] = (
            counts.get(str(row.get("effective_status")), 0) + 1
        )
    counts["total"] = len(rows)
    return counts


def posture_score(counts: Mapping[str, int]) -> dict[str, int]:
    """Score over the effective buckets the page itself displays.

    Judged = pass + fail + warning. Not-applicable, excepted,
    missing-evidence, and unknown all stay out of the denominator —
    the engine-level ``PolicyReport.score`` counts not-applicable
    passes, so it would disagree with the tiles shown beside it.
    """

    judged = (
        int(counts.get("pass", 0)) + int(counts.get("fail", 0))
        + int(counts.get("warning", 0))
    )
    score = (
        int(round(100 * int(counts.get("pass", 0)) / judged)) if judged else 0
    )
    return {"score": score, "judged": judged}


def heatmap(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per-policy status counts — the compact visual summary."""

    cells: dict[str, dict[str, Any]] = {}
    for row in rows:
        policy = row.get("policy") or {}
        policy_id = str(policy.get("policy_id"))
        entry = cells.setdefault(policy_id, {
            "policy_id": policy_id,
            "name": str(policy.get("name")),
            "severity": str(policy.get("severity")),
            "counts": {status: 0 for status in EFFECTIVE_STATUSES},
            "total": 0,
        })
        entry["counts"][str(row.get("effective_status"))] += 1
        entry["total"] += 1
    return sorted(
        cells.values(),
        key=lambda entry: (-entry["counts"]["fail"], entry["name"].casefold()),
    )


def export_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        policy = row.get("policy") or {}
        result = row.get("result") or {}
        out.append({
            "policy_id": str(policy.get("policy_id") or ""),
            "policy": str(policy.get("name") or ""),
            "category": str(policy.get("category") or ""),
            "severity": str(policy.get("severity") or ""),
            "device": str(row.get("hostname") or ""),
            "site": str(row.get("site") or ""),
            "platform": str(row.get("platform") or ""),
            "status": str(row.get("effective_status") or ""),
            "owner": str(row.get("owner") or ""),
            "evidence_fresh": {True: "fresh", False: "stale"}.get(
                row.get("evidence_fresh"), "unknown"
            ),
            "conclusion": str(result.get("conclusion") or ""),
            "network": str(row.get("network") or ""),
        })
    return out
