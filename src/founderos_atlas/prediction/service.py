"""Prediction service: predict a change against a scope's real evidence.

``predict_change`` gathers everything the simulator needs from the
artifacts a profile's discoveries already produced — topology snapshot,
history (freshness, target instability), intelligence report (current
health), captured configuration, site catalog — and never invents data:
missing evidence lowers confidence and appears in the prediction's
unknowns. The API is generic; future change types flow through the same
entry point.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from founderos_atlas.config import safe_artifact_name
from founderos_atlas.history import HistoryRepository
from founderos_atlas.sites import SiteCatalog, SiteInferenceEngine

from .models import ChangeRequest, Prediction
from .simulator import predict


STALE_AFTER_HOURS = 24


def predict_change(
    request: ChangeRequest,
    *,
    output_dir: str | Path,
    history_root: str | Path,
    generated_at: str,
    site_catalog: SiteCatalog | None = None,
    seed_addresses: tuple[str, ...] = (),
    fresh: bool | None = None,
    history_available: bool | None = None,
    configuration_captured: bool | None = None,
) -> Prediction:
    """Predict one change using the scope's current evidence on disk.

    ``seed_addresses`` are the profile's proven entry addresses; together
    with the snapshot's per-device management address they drive the
    management-plane reachability evaluation (PR-036C).

    ``fresh``, ``history_available``, and ``configuration_captured`` may
    be supplied by callers whose evidence lives outside this scope's
    history (the enterprise federation layer, PR-037A, derives them from
    every contributing profile); when omitted they are derived from the
    scope's own artifacts exactly as before.
    """

    out = Path(output_dir)
    snapshot = _read_json(out / "topology_snapshot.json")
    records = HistoryRepository(history_root).load().records[:5]
    if history_available is None:
        history_available = bool(records)
    if fresh is None:
        fresh = _is_fresh(
            records[0].completed_at if records else None, generated_at
        )
    if configuration_captured is None:
        configuration_captured = (
            out / "configs" / safe_artifact_name(request.target_device)
            / "running_config.txt"
        ).is_file()
    intelligence = _read_json(out / "intelligence_report.json") or {}
    health = (intelligence.get("health") or {}).get("score")
    health_score = int(health) if isinstance(health, (int, float)) else None
    historically_unstable = _target_unstable(request.target_device, snapshot, records)
    device_sites = _site_lookup(snapshot, site_catalog)
    return predict(
        request,
        snapshot=snapshot,
        generated_at=generated_at,
        history_available=history_available,
        configuration_captured=configuration_captured,
        fresh=fresh,
        health_score=health_score,
        historically_unstable=historically_unstable,
        device_sites=device_sites,
        seed_addresses=seed_addresses,
    )


def render_prediction_json(prediction: Prediction) -> str:
    return (
        json.dumps(
            prediction.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def render_prediction_markdown(prediction: Prediction) -> str:
    request = prediction.change_request
    lines = [
        "# Atlas Change Prediction",
        "",
        f"- Proposed change: {request.change_type} — {request.subject}",
    ]
    if request.reason:
        lines.append(f"- Reason: {request.reason}")
    if request.maintenance_window:
        lines.append(f"- Maintenance window: {request.maintenance_window}")
    if request.requester:
        lines.append(f"- Requester: {request.requester}")
    lines.extend(
        (
            f"- Generated: {prediction.generated_at}",
            f"- Predicted risk: **{prediction.risk.level}** "
            f"(score {prediction.risk.score})",
            f"- Confidence: {prediction.confidence.band.title()} "
            f"({prediction.confidence.percent}%)",
            f"- Recommendation: **{prediction.advice.action}**",
            "",
            "## Predicted Outcomes",
            "",
        )
    )
    for outcome in prediction.outcomes:
        lines.append(f"- ({outcome.likelihood}) {outcome.description}")
    lines.extend(("", "## Blast Radius", ""))
    blast = prediction.blast_radius
    lines.append(f"- {blast.summary}")
    if blast.affected_devices:
        lines.append(f"- Devices: {', '.join(blast.affected_devices)}")
    if blast.affected_sites:
        lines.append(f"- Sites: {', '.join(blast.affected_sites)}")
    impact = blast.attributes.get("estimated_health_impact")
    if isinstance(impact, int) and impact < 0:
        lines.append(f"- Projected enterprise health impact: {impact} point(s)")
    if prediction.planes:
        lines.extend(("", "## Plane Impact", ""))
        for plane in prediction.planes:
            lines.extend(
                (
                    f"### {plane.plane.title()} Plane — "
                    f"{plane.status.replace('_', ' ')} "
                    f"({plane.confidence_band}, {plane.confidence_percent}%)",
                    "",
                    plane.explanation,
                    "",
                )
            )
            for item in plane.evidence:
                lines.append(f"- Evidence: {item}")
            for item in plane.missing_evidence:
                lines.append(f"- Missing evidence: {item}")
            if plane.affected:
                lines.append(f"- Affected: {', '.join(plane.affected)}")
    lines.extend(("", "## Risk Factors", ""))
    for factor in prediction.risk.factors:
        lines.append(f"- {factor.points:+d} {factor.name}: {factor.detail}")
    lines.extend(("", "## Why", ""))
    lines.extend(
        f"{index}. {line}"
        for index, line in enumerate(prediction.explanation, start=1)
    )
    lines.extend(("", "## Recommendation", "", f"**{prediction.advice.action}**", ""))
    lines.extend(f"- {reason}" for reason in prediction.advice.reasons)
    lines.extend(("", "## Rollback", ""))
    rollback = prediction.rollback
    lines.append(
        f"- Complexity: {rollback.complexity} "
        f"({'reversible' if rollback.reversible else 'NOT reversible'})"
    )
    lines.extend(f"- Prerequisite: {item}" for item in rollback.prerequisites)
    if prediction.unknowns:
        lines.extend(("", "## What Atlas Cannot See", ""))
        lines.extend(f"- {item}" for item in prediction.unknowns)
    if prediction.evidence_refs:
        lines.extend(
            ("", "## Supporting Evidence", "")
        )
        lines.extend(f"- {item}" for item in prediction.evidence_refs)
    return "\n".join(lines) + "\n"


# -- internals -----------------------------------------------------------------


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_fresh(last_completed: str | None, generated_at: str) -> bool:
    if not last_completed:
        return False
    try:
        completed = datetime.fromisoformat(last_completed)
        now = datetime.fromisoformat(generated_at)
    except ValueError:
        return False
    return (now - completed).total_seconds() <= STALE_AFTER_HOURS * 3600


def _target_unstable(device: str, snapshot: dict | None, records) -> bool:
    """Whether the target device failed in multiple recent discoveries."""

    addresses = {device.casefold()}
    for entry in (snapshot or {}).get("devices") or ():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("hostname") or "").casefold() == device.casefold():
            ip = entry.get("management_ip")
            if ip:
                addresses.add(str(ip).casefold())
    failures = 0
    for record in records:
        if any(str(host).casefold() in addresses for host in record.failures):
            failures += 1
    return failures >= 2


def _site_lookup(
    snapshot: dict | None, catalog: SiteCatalog | None
) -> dict[str, str]:
    if catalog is None or not catalog.sites or not isinstance(snapshot, dict):
        return {}
    engine = SiteInferenceEngine(catalog)
    lookup: dict[str, str] = {}
    for device in snapshot.get("devices") or ():
        if not isinstance(device, dict):
            continue
        hostname = str(device.get("hostname") or "")
        if not hostname:
            continue
        assignment = engine.assign(
            hostname=hostname,
            management_ips=(str(device.get("management_ip")),)
            if device.get("management_ip")
            else (),
        )
        if assignment.site_id:
            lookup[hostname] = assignment.site_id
    return lookup
