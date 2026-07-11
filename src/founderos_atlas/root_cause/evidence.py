"""Evidence normalization: every artifact becomes citable evidence items.

Sources: configuration change reports, operational state reports, topology
change reports, discovery failures, and incident reports. Items carry the
run timestamp, a causal rank, affected devices/interfaces, and the artifact
they came from — deterministic ids, deterministic order, secrets already
masked upstream.
"""

from __future__ import annotations

import re

from .models import (
    CATEGORY_CONFIGURATION,
    CATEGORY_DISCOVERY,
    CATEGORY_INCIDENT,
    CATEGORY_INTERFACE,
    CATEGORY_PROTOCOL,
    CATEGORY_TOPOLOGY,
    QUALITY_DERIVED,
    QUALITY_DIRECT,
    EvidenceItem,
)


_INTERFACE_TOKEN = re.compile(
    r"\b((?:GigabitEthernet|TenGigabitEthernet|FastEthernet|Ethernet|Serial|"
    r"Loopback|Tunnel|Vlan|Port-channel|Gi|Te|Fa|Po)[0-9][0-9/\.]*)\b",
    re.IGNORECASE,
)

_AUTH_MARKERS = ("authentication", "username and password")


def build_evidence(
    *,
    observed_at: str,
    state_report: dict | None = None,
    topology_report: dict | None = None,
    config_report: dict | None = None,
    incident_report: dict | None = None,
    failed_details: tuple[tuple[str, str], ...] = (),
) -> tuple[EvidenceItem, ...]:
    """Normalize one discovery interval's artifacts into evidence items."""

    items: list[EvidenceItem] = []

    for device_entry in (config_report or {}).get("reports") or ():
        if not isinstance(device_entry, dict):
            continue
        hostname = str(device_entry.get("hostname") or "unknown")
        for index, change in enumerate(device_entry.get("changes") or ()):
            if not isinstance(change, dict):
                continue
            lines = [
                str(line)
                for line in (
                    tuple(change.get("added_lines") or ())
                    + tuple(change.get("removed_lines") or ())
                )
            ]
            interfaces = _interfaces_in(
                " ".join([str(change.get("summary") or ""), *lines])
            )
            items.append(
                EvidenceItem(
                    evidence_id=f"config:{hostname}:{index}",
                    category=CATEGORY_CONFIGURATION,
                    observed_at=observed_at,
                    description=(
                        f"Configuration change on {hostname}: "
                        f"{change.get('summary')}"
                    ),
                    source="config_change_report.json",
                    devices=(hostname,),
                    interfaces=interfaces,
                    attributes={
                        "severity": str(change.get("severity") or "low"),
                        "category": str(change.get("category") or "other"),
                        "added_lines": lines[:6],  # masked upstream
                    },
                )
            )

    for index, change in enumerate((state_report or {}).get("changes") or ()):
        if not isinstance(change, dict):
            continue
        hostname = str(change.get("hostname") or "unknown")
        interface = str(change.get("interface") or "unknown")
        field_name = str(change.get("field") or "status")
        category = CATEGORY_PROTOCOL if field_name == "protocol" else CATEGORY_INTERFACE
        items.append(
            EvidenceItem(
                evidence_id=f"state:{hostname}:{interface}:{field_name}",
                category=category,
                observed_at=observed_at,
                description=(
                    f"{interface} on {hostname}: {field_name} "
                    f"{change.get('previous_value')} -> {change.get('current_value')}"
                ),
                source="state_change_report.json",
                devices=(hostname,),
                interfaces=(interface,),
                attributes={
                    "event": str(change.get("event") or "informational"),
                    "severity": str(change.get("severity") or "low"),
                    "field": field_name,
                    "previous_value": str(change.get("previous_value")),
                    "current_value": str(change.get("current_value")),
                },
            )
        )

    topology = topology_report or {}
    for hostname in topology.get("removed_devices") or ():
        items.append(
            EvidenceItem(
                evidence_id=f"topology:removed:{hostname}",
                category=CATEGORY_TOPOLOGY,
                observed_at=observed_at,
                description=f"{hostname} is no longer discovered",
                source="change_report.json",
                devices=(str(hostname),),
                attributes={"change": "removed"},
            )
        )
    for hostname in topology.get("new_devices") or ():
        items.append(
            EvidenceItem(
                evidence_id=f"topology:new:{hostname}",
                category=CATEGORY_TOPOLOGY,
                observed_at=observed_at,
                description=f"{hostname} was discovered for the first time",
                source="change_report.json",
                devices=(str(hostname),),
                attributes={"change": "new"},
            )
        )

    for host, detail in failed_details:
        auth = any(marker in detail.casefold() for marker in _AUTH_MARKERS)
        items.append(
            EvidenceItem(
                evidence_id=f"discovery:{host}",
                category=CATEGORY_DISCOVERY,
                observed_at=observed_at,
                description=f"{host} failed discovery: {detail}",
                source="discovery",
                devices=(str(host),),
                attributes={"auth_failure": auth, "detail": str(detail)},
            )
        )

    if incident_report is not None:
        items.append(
            EvidenceItem(
                evidence_id="incident:latest",
                category=CATEGORY_INCIDENT,
                observed_at=str(incident_report.get("generated_at") or observed_at),
                description=(
                    f"Incident on file: {incident_report.get('title', 'untitled')}"
                ),
                source="incident_report.json",
                quality=QUALITY_DERIVED,
                devices=tuple(
                    str(device)
                    for device in incident_report.get("affected_devices") or ()
                ),
                attributes={"title": str(incident_report.get("title") or "")},
            )
        )

    items.sort(key=lambda item: (item.causal_rank, item.evidence_id))
    return tuple(items)


def _interfaces_in(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _INTERFACE_TOKEN.finditer(text):
        token = match.group(1)
        if token.casefold() not in (item.casefold() for item in found):
            found.append(token)
    return tuple(found)
