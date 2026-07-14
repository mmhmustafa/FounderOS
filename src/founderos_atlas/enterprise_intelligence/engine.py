"""Evidence assembly and intelligence orchestration.

``IntelligenceEvidence`` is the single, artifact-shaped input every engine
module consumes — built either in-pipeline (from the run's report objects)
or offline from the same JSON artifacts on disk, so recomputation is always
possible and always identical. ``build_intelligence`` runs health, risk,
priority, recommendation, and trend engines over it and assembles the
complete, explainable result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from founderos_atlas.history import HistoryRepository

from .health import STALE_AFTER_HOURS, score_health
from .models import EnterpriseIntelligence, Finding
from .priority import prioritize
from .recommendations import recommend
from .risk import detect_findings
from .trend import detect_trends, health_trend


_AUTH_MARKERS = ("authentication", "username and password")
RECENT_HISTORY_WINDOW = 5


@dataclass(frozen=True)
class IntelligenceEvidence:
    """Everything the intelligence engines read. Plain data, no secrets."""

    generated_at: str
    snapshot: dict | None = None
    previous_snapshot: dict | None = None
    state_report: dict | None = None
    topology_report: dict | None = None
    config_report: dict | None = None
    incident_report: dict | None = None
    failed_hosts: tuple[str, ...] = ()
    failed_details: tuple[tuple[str, str], ...] = ()  # (host, reason)
    recent_records: tuple = ()  # DiscoveryRecord, newest first
    previous_intelligence: dict | None = None
    last_completed_at: str | None = None
    baseline_available: bool = False
    _degrees: dict[str, int] = field(default_factory=dict, compare=False)
    _previous_degrees: dict[str, int] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_degrees", _degree_map(self.snapshot))
        object.__setattr__(
            self, "_previous_degrees", _degree_map(self.previous_snapshot)
        )

    # -- topology ---------------------------------------------------------

    @property
    def device_count(self) -> int:
        if self.snapshot is None:
            return 0
        return int(self.snapshot.get("device_count") or 0)

    def neighbor_count(self, hostname: str) -> int:
        return self._degrees.get(str(hostname).casefold(), 0)

    def previous_neighbor_count(self, hostname: str) -> int:
        return self._previous_degrees.get(str(hostname).casefold(), 0)

    @property
    def topology_change_count(self) -> int:
        if self.topology_report is None:
            return 0
        return int(self.topology_report.get("change_count") or 0)

    @property
    def topology_high_changes(self) -> int:
        if self.topology_report is None:
            return 0
        counts = self.topology_report.get("severity_counts") or {}
        return int(counts.get("high") or 0)

    @property
    def topology_other_changes(self) -> int:
        return max(0, self.topology_change_count - self.topology_high_changes)

    @property
    def removed_devices(self) -> tuple[str, ...]:
        if self.topology_report is None:
            return ()
        return tuple(str(name) for name in self.topology_report.get("removed_devices") or ())

    # -- operational state --------------------------------------------------

    @property
    def interfaces_down(self) -> int:
        if self.state_report is None:
            return 0
        return int(self.state_report.get("interfaces_down") or 0)

    @property
    def active_issue_count(self) -> int:
        if self.state_report is None:
            return 0
        return int(self.state_report.get("active_issue_count") or 0)

    @property
    def recovery_count(self) -> int:
        if self.state_report is None:
            return 0
        return int(self.state_report.get("recovery_count") or 0)

    @property
    def active_interface_issues(self) -> tuple[dict, ...]:
        """Active failures/degradations, one entry per interface (worst wins)."""

        if self.state_report is None:
            return ()
        by_interface: dict[tuple[str, str], dict] = {}
        for change in self.state_report.get("changes") or ():
            if not isinstance(change, dict):
                continue
            if change.get("event") not in ("failure", "degradation"):
                continue
            key = (
                str(change.get("hostname") or ""),
                str(change.get("interface") or ""),
            )
            current = by_interface.get(key)
            if current is None or (
                change.get("severity") == "high" and current.get("severity") != "high"
            ):
                by_interface[key] = change
        return tuple(by_interface[key] for key in sorted(by_interface))

    @property
    def active_issue_subjects(self) -> tuple[str, ...]:
        return tuple(
            f"{issue.get('hostname')} {issue.get('interface')}"
            for issue in self.active_interface_issues
        )

    # -- configuration -------------------------------------------------------

    @property
    def config_change_count(self) -> int:
        if self.config_report is None:
            return 0
        return int(self.config_report.get("change_count") or 0)

    @property
    def config_devices_changed(self) -> int:
        if self.config_report is None:
            return 0
        return int(self.config_report.get("devices_changed") or 0)

    @property
    def config_high_changes(self) -> int:
        if self.config_report is None:
            return 0
        counts = self.config_report.get("severity_counts") or {}
        return int(counts.get("high") or 0)

    @property
    def config_changed_devices(self) -> tuple[str, ...]:
        if self.config_report is None:
            return ()
        return tuple(
            sorted(
                str(entry.get("hostname"))
                for entry in self.config_report.get("reports") or ()
                if isinstance(entry, dict) and int(entry.get("change_count") or 0) > 0
            )
        )

    @property
    def config_high_changed_devices(self) -> tuple[str, ...]:
        if self.config_report is None:
            return ()
        names: list[str] = []
        for entry in self.config_report.get("reports") or ():
            if not isinstance(entry, dict):
                continue
            counts = entry.get("severity_counts") or {}
            if int(counts.get("high") or 0) > 0:
                names.append(str(entry.get("hostname")))
        return tuple(sorted(names))

    # -- discovery failures ----------------------------------------------------

    @property
    def auth_failed_hosts(self) -> tuple[str, ...]:
        hosts = [
            host
            for host, detail in self.failed_details
            if any(marker in detail.casefold() for marker in _AUTH_MARKERS)
        ]
        return tuple(sorted(set(hosts)))

    @property
    def discovery_statistics(self) -> dict | None:
        """The discovery statistics recorded in the graph (PR-043.8), or
        None for legacy snapshots without them."""

        metadata = (self.snapshot or {}).get("metadata") or {}
        stats = metadata.get("discovery_statistics")
        return dict(stats) if isinstance(stats, dict) else None

    @property
    def unreachable_hosts(self) -> tuple[str, ...]:
        # PR-043.10 (POLISH, Part 3): unused/candidate addresses from a CIDR
        # scan are discovery COVERAGE, never operational risks. When the
        # graph carries discovery statistics, non-authentication failures are
        # unused addresses — excluded here. A device that was genuinely
        # managed before and is now gone surfaces as a device-removed
        # finding (a baseline comparison), not a candidate scan failure.
        if self.discovery_statistics is not None:
            return ()
        auth = set(self.auth_failed_hosts)
        return tuple(sorted(set(self.failed_hosts) - auth))

    @property
    def coverage_failed_count(self) -> int:
        """Discovery-coverage shortfall for CONFIDENCE only (never health):
        reachable devices that could not be authenticated. Unused addresses
        never count."""

        stats = self.discovery_statistics
        if stats is not None:
            return int(stats.get("authentication_failures") or 0)
        return len(self.failed_hosts)

    @property
    def recurring_unstable_hosts(self) -> tuple[str, ...]:
        """Hosts that failed in two or more of the recent discoveries.

        PR-043.10 (POLISH, Part 3): a CIDR scan re-attempts the same unused
        addresses every run, so they would look "repeatedly unstable" — but
        an empty address is discovery coverage, not an unstable device. When
        the graph carries discovery statistics, only genuine current
        failures (reachable devices that could not be authenticated) can be
        flagged as recurring instability."""

        if self.discovery_statistics is not None:
            genuine = set(self.auth_failed_hosts)
            if not genuine:
                return ()
        else:
            genuine = None
        counts: dict[str, int] = {}
        for record in self.recent_records:
            for host in set(record.failures):
                if genuine is not None and host not in genuine:
                    continue  # unused/candidate address — never instability
                counts[host] = counts.get(host, 0) + 1
        current = set(self.failed_hosts)
        return tuple(
            sorted(
                host
                for host, seen in counts.items()
                if seen >= 2 or (seen >= 1 and host in current)
            )
        )

    # -- incidents / freshness / history ---------------------------------------

    @property
    def incident_open(self) -> bool:
        return self.incident_report is not None

    @property
    def is_stale(self) -> bool:
        if not self.last_completed_at:
            return False
        try:
            completed = datetime.fromisoformat(self.last_completed_at)
            now = datetime.fromisoformat(self.generated_at)
        except ValueError:
            return False
        return (now - completed).total_seconds() > STALE_AFTER_HOURS * 3600

    @property
    def previous_score(self) -> int | None:
        if self.previous_intelligence is None:
            return None
        health = self.previous_intelligence.get("health") or {}
        score = health.get("score")
        return int(score) if isinstance(score, (int, float)) else None

    @property
    def previous_config_change_count(self) -> int | None:
        if self.previous_intelligence is None:
            return None
        basis = self.previous_intelligence.get("basis") or {}
        value = basis.get("config_change_count")
        return int(value) if isinstance(value, (int, float)) else None


def build_intelligence(evidence: IntelligenceEvidence) -> EnterpriseIntelligence:
    """Run every engine over the evidence; fully deterministic."""

    health = score_health(evidence)
    findings = detect_findings(evidence)
    priorities = prioritize(findings)
    recommendations = recommend(priorities, evidence)
    trend, trend_detail = health_trend(health.score, evidence.previous_score)
    trends = detect_trends(evidence, health.score)
    improvement, regression = _factor_deltas(health, evidence.previous_intelligence)
    return EnterpriseIntelligence(
        generated_at=evidence.generated_at,
        health=health,
        trend=trend,
        trend_detail=trend_detail,
        findings=findings,
        priorities=priorities,
        recommendations=recommendations,
        trends=trends,
        changes_summary=_changes_summary(evidence),
        biggest_improvement=improvement,
        biggest_regression=regression,
        suggested_investigation=(
            recommendations[0].next_step if recommendations else None
        ),
        previous_score=evidence.previous_score,
        basis={
            "device_count": evidence.device_count,
            "failed_devices": len(evidence.failed_hosts),
            "interfaces_down": evidence.interfaces_down,
            "active_issues": evidence.active_issue_count,
            "topology_changes": evidence.topology_change_count,
            "config_change_count": evidence.config_change_count,
            "config_devices_changed": evidence.config_devices_changed,
            "baseline_available": evidence.baseline_available,
            "history_window": len(evidence.recent_records),
        },
    )


def load_evidence(
    output_dir: str | Path,
    history_root: str | Path,
    *,
    generated_at: str,
) -> IntelligenceEvidence:
    """Rebuild evidence from the artifacts on disk (GUI / offline use)."""

    out = Path(output_dir)
    repository = HistoryRepository(history_root)
    records = repository.load().records[:RECENT_HISTORY_WINDOW]
    latest = records[0] if records else None
    previous_intelligence = None
    previous_snapshot = None
    if len(records) >= 2:
        previous_dir = repository.record_directory(records[1].record_id)
        previous_intelligence = _read_json(previous_dir / "intelligence_report.json")
        previous_snapshot = _read_json(previous_dir / "topology_snapshot.json")
    snapshot = _read_json(out / "topology_snapshot.json")
    failed_hosts: tuple[str, ...] = ()
    if snapshot is not None:
        metadata = snapshot.get("metadata") or {}
        failed_hosts = tuple(str(host) for host in metadata.get("failed_hosts") or ())
    return IntelligenceEvidence(
        generated_at=generated_at,
        snapshot=snapshot,
        previous_snapshot=previous_snapshot,
        state_report=_read_json(out / "state_change_report.json"),
        topology_report=_read_json(out / "change_report.json"),
        config_report=_read_json(out / "config_change_report.json"),
        incident_report=_read_json(out / "incident_report.json"),
        failed_hosts=failed_hosts,
        recent_records=tuple(records),
        previous_intelligence=previous_intelligence,
        last_completed_at=latest.completed_at if latest is not None else None,
        baseline_available=len(records) >= 2,
    )


def _changes_summary(evidence: IntelligenceEvidence) -> tuple[str, ...]:
    if not evidence.baseline_available:
        return ("First discovery of this network — baseline established.",)
    lines = [
        f"Topology changes: {evidence.topology_change_count}",
        f"Configuration changes: {evidence.config_change_count} "
        f"across {evidence.config_devices_changed} device(s)",
        f"Operational: {evidence.active_issue_count} active issue(s), "
        f"{evidence.recovery_count} recovery(ies)",
    ]
    if evidence.removed_devices:
        lines.append("No longer discovered: " + ", ".join(evidence.removed_devices))
    return tuple(lines)


def _factor_deltas(
    health, previous_intelligence: dict | None
) -> tuple[str | None, str | None]:
    """Biggest improvement/regression: factor point deltas versus last run."""

    if previous_intelligence is None:
        return None, None
    previous = {
        str(factor.get("name")): int(factor.get("points") or 0)
        for factor in (previous_intelligence.get("health") or {}).get("factors") or ()
        if isinstance(factor, dict)
    }
    current = {factor.name: factor.points for factor in health.factors}
    deltas: dict[str, int] = {}
    details: dict[str, str] = {
        factor.name: factor.detail for factor in health.factors
    }
    for name in set(previous) | set(current):
        deltas[name] = current.get(name, 0) - previous.get(name, 0)
    improvement = regression = None
    if deltas:
        best = max(sorted(deltas), key=lambda name: deltas[name])
        worst = min(sorted(deltas), key=lambda name: deltas[name])
        if deltas[best] > 0:
            improvement = (
                f"{best} (+{deltas[best]}): "
                + details.get(best, "cleared since the previous discovery")
            )
        if deltas[worst] < 0:
            regression = (
                f"{worst} ({deltas[worst]}): "
                + details.get(worst, "new since the previous discovery")
            )
    return improvement, regression


def _degree_map(snapshot: dict | None) -> dict[str, int]:
    """Logical neighbor count per hostname, from snapshot edges."""

    if not isinstance(snapshot, dict):
        return {}
    hostname_by_id = {
        str(device.get("device_id")): str(device.get("hostname"))
        for device in snapshot.get("devices") or ()
        if isinstance(device, dict)
    }
    neighbors: dict[str, set[str]] = {}
    for edge in snapshot.get("edges") or ():
        if not isinstance(edge, dict):
            continue
        local = hostname_by_id.get(
            str(edge.get("local_device_id")), str(edge.get("local_device_id"))
        ).casefold()
        remote = str(edge.get("remote_hostname")).casefold()
        if local == remote:
            continue
        neighbors.setdefault(local, set()).add(remote)
        neighbors.setdefault(remote, set()).add(local)
    return {hostname: len(peers) for hostname, peers in neighbors.items()}


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
