"""Calculate every health dimension from Atlas artifacts.

The builder is deliberately a pure function of its inputs (artifact
dicts plus a clock string) so every rule is unit-testable and every
page that renders health goes through the identical calculation.

Every dimension records its denominator, the timestamp of the evidence
it judged, and a summary sentence explaining the verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from founderos_atlas.federation import contribution_is_fresh
from founderos_atlas.federation.service import STALE_AFTER_HOURS

from .model import (
    DIMENSION_DRIFT,
    DIMENSION_EVIDENCE,
    DIMENSION_FRESHNESS,
    DIMENSION_IDENTITY,
    DIMENSION_INCIDENTS,
    DIMENSION_POLICY,
    DIMENSION_REACHABILITY,
    STATE_CRITICAL,
    STATE_DEGRADED,
    STATE_HEALTHY,
    STATE_STALE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    HealthAssessment,
    HealthDimension,
)


def assess_network_health(
    *,
    scope_id: str,
    scope_label: str,
    now: str,
    snapshot: Mapping[str, Any] | None,
    configurations_collected: int = 0,
    configuration_collection_enabled: bool | None = None,
    config_change_report: Mapping[str, Any] | None = None,
    state_change_report: Mapping[str, Any] | None = None,
    incident_report: Mapping[str, Any] | None = None,
    policy_summary: Mapping[str, Any] | None = None,
) -> HealthAssessment:
    """The canonical health of one network scope.

    ``policy_summary`` is the PolicyReport aggregate (``passed``,
    ``failed``, ``warnings``, ``unknown``, ``judged``) or ``None`` when
    the policy engine has never produced a verdict for this scope.
    """

    dimensions = (
        _reachability(snapshot),
        _freshness(snapshot, now),
        _evidence_coverage(
            snapshot, configurations_collected, configuration_collection_enabled
        ),
        _policy(policy_summary),
        _drift(config_change_report),
        _incidents(state_change_report, incident_report),
        _identity(snapshot),
    )
    return HealthAssessment(
        scope_id=scope_id,
        scope_label=scope_label,
        generated_at=now,
        dimensions=dimensions,
    )


def _snapshot_time(snapshot: Mapping[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    return str(snapshot.get("created_at") or "") or None


def _reachability(snapshot: Mapping[str, Any] | None) -> HealthDimension:
    """Managed devices reached on the last run vs. those that failed.

    The denominator is managed devices plus hosts Atlas tried and could
    not manage — never the swept address space (an unused address is
    information, not a failure)."""

    if not snapshot:
        return HealthDimension(
            key=DIMENSION_REACHABILITY, state=STATE_UNKNOWN,
            summary="no discovery has run, so reachability is unmeasured",
        )
    devices = int(snapshot.get("device_count") or len(snapshot.get("devices") or ()))
    metadata = snapshot.get("metadata") or {}
    statistics = metadata.get("discovery_statistics") or {}
    if statistics:
        # The discovery statistics are authoritative (PR-043.8): an unused
        # address in a swept range is information, never a failure. Only
        # authentication failures count against reachability.
        failures = int(statistics.get("authentication_failures") or 0)
        failed = tuple(
            f"{failures} authentication failure(s)"
        ) if failures else ()
        managed = int(statistics.get("managed_devices") or devices)
        denominator = managed + failures
        if denominator == 0:
            return HealthDimension(
                key=DIMENSION_REACHABILITY, state=STATE_UNKNOWN,
                summary="the last discovery reached no managed devices",
                observed_at=_snapshot_time(snapshot),
            )
        if failures:
            return HealthDimension(
                key=DIMENSION_REACHABILITY, state=STATE_DEGRADED,
                summary=(
                    f"{failures} address(es) answered but could not be "
                    "authenticated on the last discovery"
                ),
                numerator=managed, denominator=denominator, unit="devices",
                observed_at=_snapshot_time(snapshot),
            )
        return HealthDimension(
            key=DIMENSION_REACHABILITY, state=STATE_HEALTHY,
            summary=(
                "every reachable device authenticated on the last discovery"
                " (unused addresses are information, not failures)"
            ),
            numerator=managed, denominator=denominator, unit="devices",
            observed_at=_snapshot_time(snapshot),
        )
    failed = tuple(str(host) for host in metadata.get("failed_hosts") or ())
    denominator = devices + len(failed)
    if denominator == 0:
        return HealthDimension(
            key=DIMENSION_REACHABILITY, state=STATE_UNKNOWN,
            summary="the last discovery reached no managed devices",
            observed_at=_snapshot_time(snapshot),
        )
    if failed:
        return HealthDimension(
            key=DIMENSION_REACHABILITY, state=STATE_DEGRADED,
            summary=(
                f"{len(failed)} previously-known host(s) could not be "
                "managed on the last discovery"
            ),
            numerator=devices, denominator=denominator, unit="devices",
            observed_at=_snapshot_time(snapshot),
            evidence=tuple(f"failed: {host}" for host in failed[:6]),
        )
    return HealthDimension(
        key=DIMENSION_REACHABILITY, state=STATE_HEALTHY,
        summary="every managed device was reached on the last discovery",
        numerator=devices, denominator=denominator, unit="devices",
        observed_at=_snapshot_time(snapshot),
    )


def _freshness(snapshot: Mapping[str, Any] | None, now: str) -> HealthDimension:
    if not snapshot:
        return HealthDimension(
            key=DIMENSION_FRESHNESS, state=STATE_UNKNOWN,
            summary="no discovery has run yet",
        )
    observed_at = _snapshot_time(snapshot)
    if contribution_is_fresh(observed_at, now):
        return HealthDimension(
            key=DIMENSION_FRESHNESS, state=STATE_HEALTHY,
            summary=(
                f"evidence is within the {STALE_AFTER_HOURS}h freshness window"
            ),
            observed_at=observed_at,
        )
    return HealthDimension(
        key=DIMENSION_FRESHNESS, state=STATE_STALE,
        summary=(
            f"the last discovery is older than {STALE_AFTER_HOURS}h; "
            "current state may differ"
        ),
        observed_at=observed_at,
    )


def _evidence_coverage(
    snapshot: Mapping[str, Any] | None,
    configurations_collected: int,
    collection_enabled: bool | None,
) -> HealthDimension:
    if not snapshot:
        return HealthDimension(
            key=DIMENSION_EVIDENCE, state=STATE_UNKNOWN,
            summary="no discovery has run, so there is no evidence to measure",
        )
    devices = int(snapshot.get("device_count") or len(snapshot.get("devices") or ()))
    if devices == 0:
        return HealthDimension(
            key=DIMENSION_EVIDENCE, state=STATE_UNKNOWN,
            summary="no managed devices, so coverage has no denominator",
            observed_at=_snapshot_time(snapshot),
        )
    if collection_enabled is False and configurations_collected == 0:
        return HealthDimension(
            key=DIMENSION_EVIDENCE, state=STATE_UNAVAILABLE,
            summary="configuration collection is disabled for this scope",
            observed_at=_snapshot_time(snapshot),
        )
    if configurations_collected >= devices:
        return HealthDimension(
            key=DIMENSION_EVIDENCE, state=STATE_HEALTHY,
            summary="a configuration is held for every managed device",
            numerator=min(configurations_collected, devices),
            denominator=devices, unit="configs",
            observed_at=_snapshot_time(snapshot),
        )
    return HealthDimension(
        key=DIMENSION_EVIDENCE, state=STATE_DEGRADED,
        summary=(
            f"configurations are held for {configurations_collected} of "
            f"{devices} managed device(s)"
        ),
        numerator=configurations_collected, denominator=devices, unit="configs",
        observed_at=_snapshot_time(snapshot),
    )


def _policy(policy_summary: Mapping[str, Any] | None) -> HealthDimension:
    if not policy_summary or not int(policy_summary.get("total") or 0):
        return HealthDimension(
            key=DIMENSION_POLICY, state=STATE_UNAVAILABLE,
            summary="the policy engine has not evaluated this scope",
        )
    judged = int(policy_summary.get("judged") or 0)
    passed = int(policy_summary.get("passed") or 0)
    failed = int(policy_summary.get("failed") or 0)
    warnings = int(policy_summary.get("warnings") or 0)
    unknown = int(policy_summary.get("unknown") or 0)
    observed_at = policy_summary.get("generated_at")
    if judged == 0:
        return HealthDimension(
            key=DIMENSION_POLICY, state=STATE_UNKNOWN,
            summary=(
                f"all {unknown} policy evaluation(s) were Unknown — Atlas "
                "held no evidence to judge them"
            ),
            observed_at=observed_at,
        )
    if failed:
        return HealthDimension(
            key=DIMENSION_POLICY, state=STATE_DEGRADED,
            summary=f"{failed} policy evaluation(s) failed",
            numerator=passed, denominator=judged, unit="passed",
            observed_at=observed_at,
        )
    if warnings:
        return HealthDimension(
            key=DIMENSION_POLICY, state=STATE_DEGRADED,
            summary=f"{warnings} policy evaluation(s) carry warnings",
            numerator=passed, denominator=judged, unit="passed",
            observed_at=observed_at,
        )
    summary = "every judged policy evaluation passed"
    if unknown:
        summary += f" ({unknown} could not be judged and are excluded)"
    return HealthDimension(
        key=DIMENSION_POLICY, state=STATE_HEALTHY,
        summary=summary,
        numerator=passed, denominator=judged, unit="passed",
        observed_at=observed_at,
    )


def _drift(config_change_report: Mapping[str, Any] | None) -> HealthDimension:
    if config_change_report is None:
        return HealthDimension(
            key=DIMENSION_DRIFT, state=STATE_UNAVAILABLE,
            summary=(
                "drift needs two configuration collections; no comparison "
                "report exists yet"
            ),
        )
    changes = int(config_change_report.get("change_count") or 0)
    devices_changed = int(config_change_report.get("devices_changed") or 0)
    observed_at = config_change_report.get("generated_at")
    if changes == 0:
        return HealthDimension(
            key=DIMENSION_DRIFT, state=STATE_HEALTHY,
            summary="no configuration drift since the previous collection",
            numerator=0, denominator=devices_changed or None, unit="changes",
            observed_at=observed_at,
        )
    return HealthDimension(
        key=DIMENSION_DRIFT, state=STATE_DEGRADED,
        summary=(
            f"{changes} configuration change(s) across "
            f"{devices_changed} device(s) since the previous collection"
        ),
        numerator=changes, denominator=None, unit="changes",
        observed_at=observed_at,
    )


def _incidents(
    state_change_report: Mapping[str, Any] | None,
    incident_report: Mapping[str, Any] | None,
) -> HealthDimension:
    if state_change_report is None and incident_report is None:
        return HealthDimension(
            key=DIMENSION_INCIDENTS, state=STATE_UNAVAILABLE,
            summary="no operational-state or incident report exists yet",
        )
    operational = state_change_report or {}
    active = int(operational.get("active_issue_count") or 0)
    interfaces_down = int(operational.get("interfaces_down") or 0)
    current_health = str(operational.get("current_health") or "")
    observed_at = operational.get("generated_at") or (
        incident_report or {}
    ).get("generated_at")
    if current_health == "Critical":
        return HealthDimension(
            key=DIMENSION_INCIDENTS, state=STATE_CRITICAL,
            summary=(
                f"operational state is Critical "
                f"({interfaces_down} interface(s) down)"
            ),
            numerator=active, denominator=None, unit="active issues",
            observed_at=observed_at,
        )
    if active:
        return HealthDimension(
            key=DIMENSION_INCIDENTS, state=STATE_DEGRADED,
            summary=f"{active} active operational issue(s)",
            numerator=active, denominator=None, unit="active issues",
            observed_at=observed_at,
        )
    return HealthDimension(
        key=DIMENSION_INCIDENTS, state=STATE_HEALTHY,
        summary="no active operational issues",
        numerator=0, denominator=None, unit="active issues",
        observed_at=observed_at,
    )


def _identity(snapshot: Mapping[str, Any] | None) -> HealthDimension:
    if not snapshot:
        return HealthDimension(
            key=DIMENSION_IDENTITY, state=STATE_UNKNOWN,
            summary="no discovery has run, so identity confidence is unmeasured",
        )
    warnings = len(snapshot.get("warnings") or ())
    devices = int(snapshot.get("device_count") or len(snapshot.get("devices") or ()))
    hostnames = {
        str(device.get("hostname") or "").casefold()
        for device in snapshot.get("devices") or ()
    }
    unresolved = {
        str(edge.get("remote_hostname") or "").casefold()
        for edge in snapshot.get("edges") or ()
        if str(edge.get("remote_hostname") or "").casefold() not in hostnames
    }
    observed_at = _snapshot_time(snapshot)
    problems: list[str] = []
    if unresolved:
        problems.append(f"{len(unresolved)} unresolved peer identit"
                        + ("y" if len(unresolved) == 1 else "ies"))
    if warnings:
        problems.append(f"{warnings} reconciliation warning(s)")
    if problems:
        return HealthDimension(
            key=DIMENSION_IDENTITY, state=STATE_DEGRADED,
            summary=" and ".join(problems),
            numerator=devices, denominator=devices + len(unresolved),
            unit="resolved endpoints",
            observed_at=observed_at,
            evidence=tuple(sorted(unresolved))[:8],
        )
    return HealthDimension(
        key=DIMENSION_IDENTITY, state=STATE_HEALTHY,
        summary="every observed endpoint resolves to a discovered device",
        numerator=devices, denominator=devices, unit="resolved endpoints",
        observed_at=observed_at,
    )
