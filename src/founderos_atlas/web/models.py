"""View-model helpers that shape backend service data for templates.

Keeps routes thin and ensures no secret ever reaches a template: profiles
carry only a credential reference, never a password.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any


NAV_ITEMS = (
    ("dashboard", "Dashboard", "/"),
    ("discovery", "Discover", "/discovery"),
    ("profiles", "Profiles", "/profiles"),
    ("credentials", "Credentials", "/credentials"),
    ("topology", "Topology", "/topology"),
    ("predict", "Predict", "/predict"),
    ("history", "History", "/history"),
    ("changes", "Changes", "/changes"),
    ("incidents", "Incidents", "/incidents"),
    ("settings", "Settings", "/settings"),
)


def format_timestamp(value: str | None) -> str:
    if not value:
        return "never"
    try:
        return datetime.fromisoformat(value).strftime("%d-%b-%Y %H:%M")
    except (ValueError, TypeError):
        return str(value)


def profile_row(profile) -> dict[str, Any]:
    """A profile as a template-safe dict — never includes a password."""

    boundary = getattr(profile, "boundary", None)
    return {
        "profile_id": profile.profile_id,
        "name": profile.name,
        "site": profile.site or "-",
        "management_ip": profile.management_ip,
        "username": profile.username,
        "max_depth": profile.max_depth,
        "max_devices": profile.max_devices,
        "collect_configuration": profile.collect_configuration,
        "last_discovery": format_timestamp(profile.last_discovery),
        "created_at": format_timestamp(profile.created_at),
        "updated_at": format_timestamp(profile.updated_at),
        "description": getattr(profile, "description", None) or "",
        "seeds_text": ", ".join(getattr(profile, "seeds", ())),
        "include_cidrs_text": ", ".join(boundary.include_cidrs) if boundary else "",
        "exclude_cidrs_text": ", ".join(boundary.exclude_cidrs) if boundary else "",
        "deny_hostnames_text": ", ".join(boundary.deny_hostnames) if boundary else "",
        "credential_sets_text": ", ".join(getattr(profile, "credential_sets", ())),
        "site_hint": getattr(profile, "site_hint", None) or "",
        "domain_hint": getattr(profile, "domain_hint", None) or "",
    }


def load_json(path: str | Path) -> dict[str, Any] | None:
    resolved = Path(path)
    if not resolved.is_file():
        return None
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, Mapping) else None


@dataclass(frozen=True)
class ChangeSummaries:
    topology: dict[str, Any] | None
    configuration: dict[str, Any] | None
    operational: dict[str, Any] | None
    incident: dict[str, Any] | None


def change_summaries(output_dir: Path) -> ChangeSummaries:
    return ChangeSummaries(
        topology=load_json(output_dir / "change_report.json"),
        configuration=load_json(output_dir / "config_change_report.json"),
        operational=load_json(output_dir / "state_change_report.json"),
        incident=load_json(output_dir / "incident_report.json"),
    )


def history_rows(history_index, *, scope_label: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for record in history_index.records:
        rows.append(
            {
                "record_id": record.record_id,
                "started_at": format_timestamp(record.started_at),
                "started_at_iso": record.started_at,
                "device_count": record.device_count,
                "relationship_count": record.relationship_count,
                "network_status": record.network_status,
                "duration_seconds": round(record.duration_seconds, 1),
                "configuration_status": record.configuration_status,
                "profile": record.profile_name or scope_label or "—",
            }
        )
    return rows


def enterprise_device_rows(topology) -> list[dict[str, Any]]:
    """Enterprise devices shaped for the topology table — never a secret."""

    rows: list[dict[str, Any]] = []
    for device in topology.devices:
        rows.append(
            {
                "hostname": device.hostname,
                "management_ips": ", ".join(device.management_ips) or "—",
                "platform": device.platform or "—",
                "site": device.site.label,
                "site_confidence": (
                    device.site.confidence
                    if device.site.confidence is not None
                    else "—"
                ),
                "networks": ", ".join(device.profile_names),
                "credential_ref": device.credential_ref or "—",
            }
        )
    return rows


def credential_set_rows(sets) -> list[dict[str, Any]]:
    """Credential sets shaped for templates — references only, no secrets."""

    rows: list[dict[str, Any]] = []
    for credential_set in sets:
        rows.append(
            {
                "set_id": credential_set.set_id,
                "name": credential_set.name,
                "entries": [
                    {
                        "entry_id": entry.entry_id,
                        "label": entry.label,
                        "username": entry.username,
                        "priority": entry.priority,
                        "scope_summary": entry.scope.summary(),
                        "last_success": format_timestamp(entry.last_success),
                        "enabled": entry.enabled,
                    }
                    for entry in credential_set.entries
                ],
            }
        )
    return rows


def prediction_targets(snapshot: dict | None) -> list[dict[str, Any]]:
    """Devices with their discovered interfaces as labeled dropdown options.

    Option values are always the canonical Atlas interface name; labels add
    admin/protocol status, IP address, description, and the connected
    neighbor when the snapshot knows them.
    """

    if not isinstance(snapshot, dict):
        return []
    neighbor_by_port: dict[tuple[str, str], str] = {}
    hostname_by_id = {
        str(device.get("device_id")): str(device.get("hostname"))
        for device in snapshot.get("devices") or ()
        if isinstance(device, dict)
    }
    for edge in snapshot.get("edges") or ():
        if not isinstance(edge, dict):
            continue
        local = hostname_by_id.get(
            str(edge.get("local_device_id")), str(edge.get("local_device_id"))
        )
        key = (local.casefold(), str(edge.get("local_interface") or "").casefold())
        neighbor_by_port.setdefault(key, str(edge.get("remote_hostname")))
    from founderos_atlas.prediction import classify_interface

    targets: list[dict[str, Any]] = []
    for device in snapshot.get("devices") or ():
        if not isinstance(device, dict):
            continue
        hostname = str(device.get("hostname") or "")
        management_ip = str(device.get("management_ip") or "")
        options: list[dict[str, str]] = []
        for interface in device.get("interfaces") or ():
            if not isinstance(interface, dict):
                continue
            name = str(interface.get("name") or "")
            if not name:
                continue
            status = str(interface.get("status") or "?")
            protocol = str(interface.get("protocol_status") or "?")
            interface_type = classify_interface(name)
            parts = [name]
            if interface_type not in ("physical", "unknown"):
                # Logical interfaces carry their semantics into the label.
                parts.append(f"[{interface_type.upper() if interface_type == 'svi' else interface_type}]")
            parts.append(f"{status}/{protocol}")
            ip = interface.get("ip_address")
            clean_ip = (
                str(ip)
                if ip and str(ip).casefold() not in ("unassigned", "none")
                else None
            )
            if clean_ip:
                parts.append(clean_ip)
                if management_ip and clean_ip == management_ip:
                    parts.append("management address")
            description = interface.get("description")
            if description:
                parts.append(str(description))
            neighbor = neighbor_by_port.get((hostname.casefold(), name.casefold()))
            if neighbor:
                parts.append(f"connected to {neighbor}")
            options.append({"name": name, "label": " — ".join(parts)})
        targets.append(
            {
                "hostname": hostname,
                "interfaces": options,
                "interface_names": ", ".join(option["name"] for option in options),
            }
        )
    targets.sort(key=lambda item: item["hostname"].casefold())
    return targets


def device_inventory(scoped_snapshots) -> list[dict[str, Any]]:
    """All Networks device inventory: the latest devices of every scope.

    ``scoped_snapshots`` is an iterable of ``(label, snapshot_dict)`` pairs.
    Pure aggregation — devices from different networks are listed side by
    side and never compared, so absence from one network can never be shown
    as removal from another.
    """

    devices: list[dict[str, Any]] = []
    for label, snapshot in scoped_snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        for device in snapshot.get("devices") or ():
            devices.append(
                {
                    "network": label,
                    "hostname": str(device.get("hostname") or "unknown"),
                    "management_ip": str(device.get("management_ip") or "—"),
                    "platform": str(device.get("platform") or "—"),
                    "os_version": str(device.get("os_version") or "—"),
                }
            )
    devices.sort(key=lambda row: (row["network"].casefold(), row["hostname"].casefold()))
    return devices
