"""Path Intelligence service: investigate against a scope's real evidence.

``investigate_path_for_scope`` gathers everything the engine needs from
the artifacts a profile's discoveries already produced — the topology
snapshot, history (freshness and last-run failures), captured
configurations — runs the investigation, writes the latest report
(JSON + Markdown), and appends the full result to the scope's
investigation history so any past investigation can be replayed exactly.

No secrets ever appear in an investigation, its reports, or its history.
"""

from __future__ import annotations

import copy
from datetime import datetime
import json
from pathlib import Path

from founderos_atlas.config import safe_artifact_name
from founderos_atlas.history import HistoryRepository

from .engine import investigate_path
from .models import PathInvestigationResult
from .policy import load_device_policies


STALE_AFTER_HOURS = 24
HISTORY_LIMIT = 50
HISTORY_FILENAME = "path_investigations.json"
REPORT_JSON = "path_investigation_report.json"
REPORT_MARKDOWN = "path_investigation_report.md"

_STATUS_LABEL = {
    "pass": "PASS",
    "warning": "WARNING",
    "failed": "FAILED",
    "unknown": "UNKNOWN",
}


def apply_permit_whatif(snapshot, device_policies, assume_permit_at):
    """Drop the captured filtering of the named devices, for a what-if run.

    Returns a (snapshot, device_policies) pair in which each named device
    has its firewall chain (snapshot metadata) and any parsed ACL removed,
    so the engine reads no filter there and the flow is treated as
    permitted. Inputs are not mutated — the snapshot is deep-copied and the
    policy map rebuilt — because the caller's originals belong to the real
    investigation. It answers "if this hop permitted the flow, does it get
    through, and where does it stop next?", not "a specific rule was
    edited": all filtering at the hop is lifted, which is a broader change
    than one rule, so the honest framing is "assumed permitted here".
    """

    permit = {str(name).casefold() for name in assume_permit_at}
    if isinstance(snapshot, dict):
        snapshot = copy.deepcopy(snapshot)
        for device in snapshot.get("devices") or ():
            if not isinstance(device, dict):
                continue
            if str(device.get("hostname") or "").casefold() in permit:
                meta = device.get("metadata")
                if isinstance(meta, dict):
                    meta.pop("firewall", None)
    if device_policies:
        device_policies = {
            key: value
            for key, value in device_policies.items()
            if key not in permit
        }
    return snapshot, device_policies


def apply_route_whatif(snapshot, withdraw_routes):
    """Withdraw the named routes from the devices that hold them.

    ``withdraw_routes`` is a sequence of (device, prefix) pairs. Each is
    removed from that device's captured routing table, so the engine's
    longest-prefix match reaches whatever the device would ACTUALLY fall
    back to — a less specific route, a default, or nothing at all, which
    is the answer the operator is asking for.

    Withdrawing a prefix is not the same as claiming the route is gone: it
    is a question ("if this were withdrawn…"), and the caller labels it as
    one. The input snapshot is deep-copied, never mutated, because the
    original belongs to the real investigation.
    """

    wanted = {
        (str(device).casefold(), str(prefix).strip())
        for device, prefix in withdraw_routes
    }
    if not isinstance(snapshot, dict):
        return snapshot
    snapshot = copy.deepcopy(snapshot)
    for device in snapshot.get("devices") or ():
        if not isinstance(device, dict):
            continue
        host = str(device.get("hostname") or "").casefold()
        metadata = device.get("metadata")
        if not isinstance(metadata, dict):
            continue
        table = metadata.get("routing_table")
        if not table:
            continue
        kept = [
            route for route in table
            if (host, str((route or {}).get("prefix") or "")) not in wanted
        ]
        if len(kept) != len(table):
            metadata["routing_table"] = kept
    return snapshot


def investigate_path_for_scope(
    source: str,
    destination: str,
    *,
    output_dir: str | Path,
    history_root: str | Path,
    generated_at: str,
    profile_id: str | None = None,
    fresh: bool | None = None,
    failed_hosts: tuple[str, ...] | None = None,
    captured_config_devices: tuple[str, ...] | None = None,
    intent: dict | None = None,
    policy_roots: tuple[Path, ...] | None = None,
    assume_permit_at: tuple[str, ...] = (),
    withdraw_routes: tuple[tuple[str, str], ...] = (),
    persist: bool = True,
) -> PathInvestigationResult:
    """Investigate one source→destination pair using scope evidence on disk.

    ``fresh``, ``failed_hosts``, and ``captured_config_devices`` may be
    supplied by callers whose evidence lives outside this scope's history
    (the enterprise federation layer, PR-037A, derives them from every
    contributing profile); when omitted they are derived from the scope's
    own artifacts exactly as before.

    ``intent`` (declared protocol/port, optionally a source address)
    turns on per-hop ACL evaluation against the captured configurations
    (packet trace Phase 2). ``policy_roots`` are the directories whose
    ``configs/`` hold those captures — defaulting to this scope's own
    ``output_dir``; the enterprise layer passes every profile's scope.
    """

    out = Path(output_dir)
    snapshot = _read_json(out / "topology_snapshot.json")
    records = HistoryRepository(history_root).load().records[:5]
    if fresh is None:
        fresh = _is_fresh(
            records[0].completed_at if records else None, generated_at
        )
    if failed_hosts is None:
        failed_hosts = tuple(
            str(host) for host in (records[0].failures if records else ())
        )
    captured = (
        captured_config_devices
        if captured_config_devices is not None
        else _captured_config_devices(out, snapshot)
    )
    device_policies = None
    if intent and (intent.get("protocol") or intent.get("port")):
        hostnames = tuple(
            str(device.get("hostname"))
            for device in ((snapshot or {}).get("devices") or ())
            if isinstance(device, dict) and device.get("hostname")
        )
        device_policies = load_device_policies(
            tuple(Path(root) for root in (policy_roots or ())) or (out,),
            hostnames,
            safe_name=safe_artifact_name,
        )

    # A what-if never persists: it must not overwrite the real report or
    # enter the investigation history.
    if assume_permit_at:
        snapshot, device_policies = apply_permit_whatif(
            snapshot, device_policies, assume_permit_at
        )
        persist = False
    if withdraw_routes:
        snapshot = apply_route_whatif(snapshot, withdraw_routes)
        persist = False

    result = investigate_path(
        source,
        destination,
        snapshot=snapshot,
        generated_at=generated_at,
        profile_id=profile_id,
        fresh=fresh,
        failed_hosts=failed_hosts,
        captured_config_devices=captured,
        intent=intent,
        device_policies=device_policies,
    )
    if persist:
        _persist(out, result)
    return result


def render_investigation_json(result: PathInvestigationResult) -> str:
    return (
        json.dumps(
            result.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def render_investigation_markdown(result: PathInvestigationResult) -> str:
    lines = [
        "# Atlas Path Investigation",
        "",
        f"- Source: {result.source}",
        f"- Destination: {result.destination}",
        f"- Result: **{result.status}**",
        f"- Generated: {result.generated_at}",
        f"- Confidence: {result.confidence_band.title()} "
        f"({result.confidence_percent}%)",
    ]
    if result.path:
        lines.append(f"- Path: {' → '.join(result.path)}")
    if result.failure_summary:
        lines.extend(("", "## Where Communication Stops", "", result.failure_summary))
    lines.extend(("", "## Investigation Story", ""))
    for step in result.steps:
        label = _STATUS_LABEL.get(step.status, step.status.upper())
        lines.append(f"{step.number}. [{label}] {step.title} — {step.detail}")
        lines.extend(f"   - Evidence: {item}" for item in step.evidence)
    if result.hops:
        lines.extend(("", "## Hop Detail", ""))
        for hop in result.hops:
            label = _STATUS_LABEL.get(hop.status, hop.status.upper())
            lines.extend(
                (
                    f"### Hop {hop.hop_number}: {hop.device} — {label} "
                    f"({hop.confidence_band}, {hop.confidence_percent}%)",
                    "",
                    hop.explanation,
                    "",
                    f"- Ingress: {hop.ingress_interface or '—'} · "
                    f"Egress: {hop.egress_interface or '—'} · "
                    f"Link: {hop.link_state} · "
                    f"Management: {hop.management_state}",
                )
            )
            lines.extend(f"- Evidence: {item}" for item in hop.evidence)
            lines.extend(
                f"- Missing evidence: {item}" for item in hop.missing_evidence
            )
    lines.extend(("", "## Recommended Next Actions", ""))
    lines.extend(f"- {item}" for item in result.recommendations)
    if result.unknowns:
        lines.extend(("", "## What Atlas Cannot See", ""))
        lines.extend(f"- {item}" for item in result.unknowns)
    if result.evidence_refs:
        lines.extend(("", "## Supporting Evidence", ""))
        lines.extend(f"- {item}" for item in result.evidence_refs)
    return "\n".join(lines) + "\n"


def load_investigation_history(output_dir: str | Path) -> list[dict]:
    """Past investigations for this scope, newest first (full results)."""

    data = _read_json_any(Path(output_dir) / HISTORY_FILENAME)
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


# -- internals -----------------------------------------------------------------


def _persist(out: Path, result: PathInvestigationResult) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / REPORT_JSON).write_text(
        render_investigation_json(result), encoding="utf-8"
    )
    (out / REPORT_MARKDOWN).write_text(
        render_investigation_markdown(result), encoding="utf-8"
    )
    history = load_investigation_history(out)
    history = [
        entry
        for entry in history
        if entry.get("investigation_id") != result.investigation_id
    ]
    history.insert(0, result.to_dict())
    del history[HISTORY_LIMIT:]
    (out / HISTORY_FILENAME).write_text(
        json.dumps(
            history, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n",
        encoding="utf-8",
    )


def _captured_config_devices(out: Path, snapshot: dict | None) -> tuple[str, ...]:
    if not isinstance(snapshot, dict):
        return ()
    found: list[str] = []
    for device in snapshot.get("devices") or ():
        if not isinstance(device, dict):
            continue
        hostname = str(device.get("hostname") or "")
        if not hostname:
            continue
        config = out / "configs" / safe_artifact_name(hostname) / "running_config.txt"
        if config.is_file():
            found.append(hostname)
    return tuple(sorted(found))


def _read_json(path: Path) -> dict | None:
    data = _read_json_any(path)
    return data if isinstance(data, dict) else None


def _read_json_any(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_fresh(last_completed: str | None, generated_at: str) -> bool:
    if not last_completed:
        return False
    try:
        completed = datetime.fromisoformat(last_completed)
        now = datetime.fromisoformat(generated_at)
    except ValueError:
        return False
    return (now - completed).total_seconds() <= STALE_AFTER_HOURS * 3600
