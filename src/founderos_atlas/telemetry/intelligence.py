"""Evidence-aware operational signals derived from normalized telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlencode

from founderos_atlas.notifications import NotificationStore

from .models import (
    FACT_BGP_STATE,
    FACT_DEVICE_HEALTH,
    FACT_INTERFACE_DISCARDS,
    FACT_INTERFACE_ERRORS,
    FACT_INTERFACE_UTILIZATION,
    FACT_LATENCY,
    FACT_LOSS,
    FACT_OSPF_STATE,
    TelemetryFact,
)


@dataclass(frozen=True)
class OperationalSignal:
    signal_id: str
    entity_id: str
    scope_id: str
    severity: str
    title: str
    explanation: str
    observed_at: str
    fact_id: str
    stale: bool
    device_id: str | None = None


def _severity(fact: TelemetryFact) -> tuple[str, str] | None:
    metadata = dict(fact.metadata)
    value = fact.value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        critical = metadata.get("critical_threshold")
        warning = metadata.get("warning_threshold")
        if critical is not None and float(value) >= float(critical):
            return "critical", f"{fact.metric} reached {value} {fact.unit}"
        if warning is not None and float(value) >= float(warning):
            return "high", f"{fact.metric} reached {value} {fact.unit}"
    state = str(value).strip().casefold()
    if fact.kind == FACT_BGP_STATE and state not in {"established", "up"}:
        return "critical", f"BGP is {value}"
    if fact.kind == FACT_OSPF_STATE and state not in {"full", "up"}:
        return "high", f"OSPF is {value}"
    if fact.kind == FACT_DEVICE_HEALTH and state in {
        "down", "critical", "failed", "unreachable",
    }:
        return "critical", f"Device health is {value}"
    if fact.kind in {
        FACT_INTERFACE_ERRORS,
        FACT_INTERFACE_DISCARDS,
        FACT_INTERFACE_UTILIZATION,
        FACT_LATENCY,
        FACT_LOSS,
    }:
        # Numeric conditions need provider- or operator-supplied thresholds.
        # Atlas does not invent a universal WAN/LAN baseline.
        return None
    return None


def derive_signals(
    facts: Iterable[TelemetryFact],
    *,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(minutes=30),
) -> tuple[OperationalSignal, ...]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    latest: dict[tuple[str, str, str], TelemetryFact] = {}
    for fact in facts:
        key = (fact.scope_id, fact.entity_id, fact.metric)
        current = latest.get(key)
        if current is None or fact.observed_at > current.observed_at:
            latest[key] = fact
    signals: list[OperationalSignal] = []
    for fact in latest.values():
        result = _severity(fact)
        if result is None:
            continue
        severity, explanation = result
        observed = datetime.fromisoformat(fact.observed_at).astimezone(
            timezone.utc
        )
        stale = moment - observed > stale_after
        signals.append(OperationalSignal(
            signal_id=f"signal:{fact.fact_id}",
            entity_id=fact.entity_id,
            scope_id=fact.scope_id,
            severity=severity,
            title=f"{fact.entity_id}: {fact.kind.replace('-', ' ')}",
            explanation=explanation,
            observed_at=fact.observed_at,
            fact_id=fact.fact_id,
            stale=stale,
            device_id=(
                str(fact.metadata["device_id"])
                if fact.metadata.get("device_id") else (
                    fact.entity_id
                    if ":" not in fact.entity_id else None
                )
            ),
        ))
    signals.sort(
        key=lambda item: (
            {"critical": 0, "high": 1}.get(item.severity, 9),
            item.entity_id.casefold(),
        )
    )
    return tuple(signals)


def reconcile_action_center(
    notifications: NotificationStore,
    signals: Iterable[OperationalSignal],
    *,
    evidence_complete: bool,
    scope_id: str | None = None,
) -> int:
    """Correlate signals and safely close absent ones only with fresh evidence."""

    values = tuple(signals)
    active_keys: dict[str, list[str]] = {}
    for signal in values:
        key = f"telemetry:{signal.scope_id}:{signal.entity_id}:{signal.fact_id}"
        active_keys.setdefault(signal.scope_id, []).append(key)
        notifications.notify(
            kind="telemetry-signal",
            title=signal.title,
            detail=signal.explanation,
            href="/telemetry?" + urlencode({
                "scope": signal.scope_id, "entity": signal.entity_id,
            }),
            audience="role:network-operator",
            dedupe_key=key,
            priority=signal.severity,
            scope_id=signal.scope_id,
            subject=signal.entity_id,
            source_refs=(signal.fact_id,),
            evidence_freshness="stale" if signal.stale else "fresh",
        )
    scopes = {scope_id} if scope_id else set(active_keys)
    resolved = 0
    for current_scope in scopes:
        if not current_scope:
            continue
        scoped = tuple(
            item for item in values if item.scope_id == current_scope
        )
        resolved += notifications.reconcile(
            kind="telemetry-signal",
            audience="role:network-operator",
            active_dedupe_keys=active_keys.get(current_scope, ()),
            evidence_complete=evidence_complete,
            evidence_stale=any(item.stale for item in scoped),
            scope_id=current_scope,
        )
    return resolved
