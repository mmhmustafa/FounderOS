"""Deterministic incident investigation over existing Atlas artifacts.

Not AI and not root-cause automation: the investigator structures an
engineer's investigation using facts Atlas already holds. Every statement
traces to an artifact; missing evidence is stated honestly, never invented.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .models import (
    EVIDENCE_CHANGES,
    EVIDENCE_CONFIG,
    EVIDENCE_HISTORY,
    EVIDENCE_TOPOLOGY,
    EVIDENCE_UNAVAILABLE,
    EvidenceItem,
    IncidentReport,
    incident_id_for,
)


NO_TOPOLOGY_CHANGE_EVIDENCE = "Topology change evidence is not available."
NO_CONFIG_CHANGE_EVIDENCE = "Configuration change evidence is not available."

_IP_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_VLAN_PATTERN = re.compile(r"\bvlan\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class IncidentArtifacts:
    """Everything the investigator may consult; all fields optional."""

    snapshot: Mapping[str, Any] | None = None
    change_report: Mapping[str, Any] | None = None
    config_change_report: Mapping[str, Any] | None = None
    brief_available: bool = False
    collected_config_hostnames: tuple[str, ...] = ()
    history_record_count: int = 0
    latest_discovery: str | None = None

    @classmethod
    def load(
        cls,
        *,
        snapshot_path: str | Path = "topology_snapshot.json",
        change_report_json: str | Path = "change_report.json",
        config_change_report: str | Path = "config_change_report.json",
        brief_path: str | Path = "morning_brief.md",
        configs_dir: str | Path = "configs",
        history_root: str | Path = Path(".atlas") / "history",
    ) -> "IncidentArtifacts":
        from founderos_atlas.history import HistoryRepository

        configs = Path(configs_dir)
        hostnames = tuple(
            sorted(
                entry.name
                for entry in (configs.iterdir() if configs.is_dir() else ())
                if entry.is_dir() and (entry / "running_config.txt").is_file()
            )
        )
        history = HistoryRepository(history_root).load()
        return cls(
            snapshot=_load_json(snapshot_path),
            change_report=_load_json(change_report_json),
            config_change_report=_load_json(config_change_report),
            brief_available=Path(brief_path).is_file(),
            collected_config_hostnames=hostnames,
            history_record_count=len(history.records),
            latest_discovery=(
                history.latest.completed_at if history.latest is not None else None
            ),
        )


class IncidentInvestigator:
    """Assemble a deterministic, evidence-based investigation."""

    def investigate(
        self,
        title: str,
        description: str,
        artifacts: IncidentArtifacts,
        *,
        generated_at: str = "unrecorded",
    ) -> IncidentReport:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        description = description.strip() or title.strip()
        text = f"{title} {description}"

        devices = _snapshot_devices(artifacts.snapshot)
        matched = _match_affected_devices(text, devices)
        explicit_match = bool(matched)
        # When nothing specific is named, the whole known network is the scope.
        affected = matched or tuple(
            sorted(
                (str(device.get("hostname")) for device in devices.values()),
                key=str.casefold,
            )
        )
        evidence: list[EvidenceItem] = []
        limitations: list[str] = [
            "This investigation uses previously collected Atlas artifacts only; "
            "no live device access was performed.",
        ]

        topology_context = self._topology_context(
            artifacts, devices, affected, evidence, limitations
        )
        related_changes = self._related_changes(
            artifacts, affected, evidence, limitations
        )
        configuration_context = self._configuration_context(
            artifacts, affected, evidence, limitations
        )
        if artifacts.history_record_count:
            evidence.append(
                EvidenceItem(
                    f"History holds {artifacts.history_record_count} preserved "
                    f"discovery record(s); latest completed "
                    f"{artifacts.latest_discovery or 'at an unrecorded time'}.",
                    EVIDENCE_HISTORY,
                )
            )

        steps = _investigation_steps(text, affected, devices, artifacts)
        recommendations = _recommendations(steps, related_changes, artifacts)
        confidence = _confidence(artifacts, explicit_match)
        if not explicit_match and devices:
            limitations.append(
                "No device named in the incident description matched the current "
                "topology; all discovered devices are treated as in scope."
            )

        snapshot_id = (
            str(artifacts.snapshot.get("snapshot_id"))
            if artifacts.snapshot is not None
            else None
        )
        return IncidentReport(
            incident_id=incident_id_for(title.strip(), description, snapshot_id),
            title=title.strip(),
            description=description,
            generated_at=generated_at,
            affected_devices=affected,
            possible_related_changes=related_changes,
            topology_context=topology_context,
            configuration_context=configuration_context,
            investigation_steps=steps,
            evidence=tuple(evidence),
            confidence=confidence,
            recommendations=recommendations,
            limitations=tuple(limitations),
        )

    def _topology_context(
        self,
        artifacts: IncidentArtifacts,
        devices: dict[str, dict[str, Any]],
        affected: tuple[str, ...],
        evidence: list[EvidenceItem],
        limitations: list[str],
    ) -> tuple[str, ...]:
        if artifacts.snapshot is None:
            limitations.append(
                "No topology snapshot is available; run discovery first."
            )
            evidence.append(
                EvidenceItem(
                    "No topology snapshot is available.", EVIDENCE_UNAVAILABLE
                )
            )
            return ()
        context = [
            f"Current topology holds {len(devices)} device(s) and "
            f"{len(_logical_links(artifacts.snapshot))} relationship(s)."
        ]
        seen_links: set[str] = set()
        for hostname in affected:
            device = devices[hostname.casefold()]
            context.append(
                f"{hostname} ({device.get('management_ip', 'unknown')}) — "
                f"platform {device.get('platform', 'unknown')}, "
                f"{len(device.get('interfaces') or ())} interface(s)."
            )
            for link in _links_for(artifacts.snapshot, hostname):
                if link in seen_links:
                    continue
                seen_links.add(link)
                context.append(link)
                evidence.append(EvidenceItem(link, EVIDENCE_TOPOLOGY))
        return tuple(context)

    def _related_changes(
        self,
        artifacts: IncidentArtifacts,
        affected: tuple[str, ...],
        evidence: list[EvidenceItem],
        limitations: list[str],
    ) -> tuple[str, ...]:
        related: list[str] = []
        if artifacts.change_report is None:
            limitations.append(NO_TOPOLOGY_CHANGE_EVIDENCE)
            evidence.append(
                EvidenceItem(NO_TOPOLOGY_CHANGE_EVIDENCE, EVIDENCE_UNAVAILABLE)
            )
        else:
            entries = tuple(artifacts.change_report.get("changes") or ())
            matched = _filter_entries(entries, affected, ("subject", "description"))
            for entry in matched[:5]:
                statement = (
                    f"[{entry.get('severity', 'info')}] {entry.get('description', '')}"
                )
                related.append(statement)
                evidence.append(EvidenceItem(statement, EVIDENCE_CHANGES))
            if not matched:
                evidence.append(
                    EvidenceItem(
                        "No topology changes were detected in the latest change report.",
                        EVIDENCE_CHANGES,
                    )
                )
        if artifacts.config_change_report is not None:
            entries = tuple(artifacts.config_change_report.get("changes") or ())
            matched = _filter_entries(entries, affected, ("hostname", "summary"))
            for entry in matched[:5]:
                statement = (
                    f"[{entry.get('severity', 'low')}] configuration: "
                    f"{entry.get('summary', '')}"
                )
                related.append(statement)
                evidence.append(EvidenceItem(statement, EVIDENCE_CONFIG))
        return tuple(related)

    def _configuration_context(
        self,
        artifacts: IncidentArtifacts,
        affected: tuple[str, ...],
        evidence: list[EvidenceItem],
        limitations: list[str],
    ) -> tuple[str, ...]:
        context: list[str] = []
        if artifacts.config_change_report is None:
            limitations.append(NO_CONFIG_CHANGE_EVIDENCE)
            evidence.append(
                EvidenceItem(NO_CONFIG_CHANGE_EVIDENCE, EVIDENCE_UNAVAILABLE)
            )
        else:
            report = artifacts.config_change_report
            counts = report.get("severity_counts") or {}
            context.append(
                f"Latest configuration change report for "
                f"{report.get('hostname', 'unknown')}: "
                f"{report.get('change_count', 0)} change(s) "
                f"(high {counts.get('high', 0)}, medium {counts.get('medium', 0)}, "
                f"low {counts.get('low', 0)})."
            )
        if artifacts.collected_config_hostnames:
            context.append(
                "Collected configurations are available for: "
                + ", ".join(artifacts.collected_config_hostnames)
                + "."
            )
        elif affected:
            context.append(
                "No collected configurations are available for offline review."
            )
        return tuple(context)


def _snapshot_devices(snapshot: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if snapshot is None:
        return {}
    devices: dict[str, dict[str, Any]] = {}
    for device in snapshot.get("devices") or ():
        devices[str(device.get("hostname", "")).casefold()] = dict(device)
    return devices


def _match_affected_devices(
    text: str, devices: dict[str, dict[str, Any]]
) -> tuple[str, ...]:
    """Match hostnames, identity aliases, and management IPs named in the text."""

    tokens = {token.casefold() for token in _TOKEN_PATTERN.findall(text)}
    ips = set(_IP_PATTERN.findall(text))
    matched: list[str] = []
    for key, device in sorted(devices.items()):
        hostname = str(device.get("hostname"))
        aliases = tuple(
            str(alias)
            for alias in ((device.get("metadata") or {}).get("identity") or {}).get(
                "aliases", ()
            )
        )
        names = {key, *(alias.casefold() for alias in aliases)}
        if names & tokens or str(device.get("management_ip")) in ips:
            matched.append(hostname)
    return tuple(matched)


def _links_for(snapshot: Mapping[str, Any], hostname: str) -> tuple[str, ...]:
    lines = []
    for (host_a, host_b), interfaces in sorted(_logical_links(snapshot).items()):
        if hostname.casefold() in (host_a.casefold(), host_b.casefold()):
            lines.append(f"{host_a} is connected to {host_b} ({interfaces})")
    return tuple(lines)


def _logical_links(snapshot: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    hostname_by_id = {
        str(device.get("device_id")): str(device.get("hostname"))
        for device in snapshot.get("devices") or ()
    }
    links: dict[tuple[str, str], str] = {}
    for edge in snapshot.get("edges") or ():
        local = hostname_by_id.get(
            str(edge.get("local_device_id")), str(edge.get("local_device_id"))
        )
        remote = str(edge.get("remote_hostname"))
        endpoints = tuple(sorted((local, remote), key=str.casefold))
        interfaces = (
            f"{edge.get('local_interface', '?')} <-> "
            f"{edge.get('remote_interface') or '?'}"
        )
        links.setdefault((endpoints[0], endpoints[1]), interfaces)
    return links


def _filter_entries(
    entries: tuple, affected: tuple[str, ...], fields: tuple[str, ...]
) -> tuple:
    if not affected:
        return entries
    needles = {name.casefold() for name in affected}
    matched = []
    for entry in entries:
        haystack = " ".join(str(entry.get(field, "")) for field in fields).casefold()
        if any(needle in haystack for needle in needles):
            matched.append(entry)
    return tuple(matched)


def _investigation_steps(
    text: str,
    affected: tuple[str, ...],
    devices: dict[str, dict[str, Any]],
    artifacts: IncidentArtifacts,
) -> tuple[str, ...]:
    lowered = text.casefold()
    subjects = ", ".join(affected) if affected else "the affected devices"
    steps: list[str] = ["Confirm the incident scope and which users or services are affected."]
    vlan_match = _VLAN_PATTERN.search(text)
    if vlan_match:
        vlan = vlan_match.group(1)
        steps.append(f"Verify VLAN {vlan} exists on {subjects}.")
        steps.append(f"Check that trunk links between the affected devices carry VLAN {vlan}.")
    if any(term in lowered for term in ("internet", "gateway", "wan", "default route")):
        steps.append(f"Check the default gateway and default route on {subjects}.")
    if any(term in lowered for term in ("slow", "latency", "performance", "degraded")):
        steps.append(f"Check interface errors, drops, and utilization on {subjects}.")
    if any(term in lowered for term in ("lost", "down", "unreachable", "connectivity", "flap")):
        steps.append(f"Verify physical links and CDP adjacencies for {subjects}.")
    if affected and artifacts.snapshot is not None:
        steps.append(f"Compare the current topology view of {subjects} against expectations.")
    steps.append("Review recent configuration changes on the affected devices.")
    if artifacts.history_record_count >= 2:
        steps.append(
            "Compare the two most recent discoveries "
            "(founderos atlas compare / config-diff --latest)."
        )
    else:
        steps.append(
            "Run a fresh discovery to capture the current network state "
            "(founderos atlas discover)."
        )
    return tuple(steps)


def _recommendations(
    steps: tuple[str, ...],
    related_changes: tuple[str, ...],
    artifacts: IncidentArtifacts,
) -> tuple[str, ...]:
    recommendations = list(steps[1:])  # scope confirmation is a step, not an action item
    if related_changes:
        recommendations.insert(
            0,
            "Review the possible related changes below first; recent changes are "
            "the most common incident cause.",
        )
    if artifacts.config_change_report is None:
        recommendations.append(
            "Collect configurations on the next discovery so configuration "
            "changes can be ruled in or out."
        )
    seen: list[str] = []
    for item in recommendations:
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def _confidence(artifacts: IncidentArtifacts, explicit_match: bool) -> str:
    if artifacts.snapshot is None:
        return "low"
    if (
        explicit_match
        and artifacts.change_report is not None
        and artifacts.config_change_report is not None
    ):
        return "high"
    return "medium"


def _load_json(path: str | Path) -> dict[str, Any] | None:
    resolved = Path(path)
    if not resolved.is_file():
        return None
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
