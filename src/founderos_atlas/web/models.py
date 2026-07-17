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


# -- Navigation (PR-047A FOCUS) ----------------------------------------------
#
# Atlas is organised around the questions an operator actually asks, not around
# the packages that answer them. Six workflows:
#
#   Mission   — "what is my status?"
#   Network   — "what is my network?"
#   Timeline  — "what changed?"
#   Policy    — "does it meet standard?"
#   Analyze   — "answer my question"
#   Setup     — "configure Atlas"
#
# Two rules keep this honest:
#
# 1. **Only the active group expands.** The sidebar shows six links; the group
#    you are in reveals its views. Six choices, not eighteen — while every view
#    remains one click from its workflow.
# 2. **Device access is not a workflow.** SSH and HTTPS are *actions on a
#    device*, offered wherever a device appears (see `_device_actions.html`).
#    They are deliberately absent here: `/console` and `/management` still work
#    and nothing was removed, but a product does not put "open a terminal" in
#    its main menu.


@dataclass(frozen=True)
class NavItem:
    """One view inside a workflow. ``key`` is what a route passes as ``active``."""

    key: str
    label: str
    href: str


@dataclass(frozen=True)
class NavGroup:
    """One workflow. ``href`` is where the group link lands (its first view)."""

    key: str
    label: str
    href: str
    items: tuple[NavItem, ...]

    @property
    def has_views(self) -> bool:
        """Whether this group is worth expanding — a single-view group is just
        a link, and rendering a one-item sub-list would be noise."""

        return len(self.items) > 1


NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup("mission", "Mission", "/", (
        NavItem("dashboard", "Overview", "/"),
        NavItem("incidents", "Incidents", "/incidents"),
    )),
    NavGroup("network", "Network", "/topology", (
        NavItem("topology", "Topology", "/topology"),
    )),
    # PR-047A: Changes / Configuration / Discoveries / Evidence were four
    # top-level items answering one question — "what changed?". They are one
    # workflow now, entered through the Timeline overview. Nothing was removed;
    # every view is intact beneath it. This is also the natural home for the
    # future Change → Impact capability.
    # PR-047B ordered these the way the work actually happens: a discovery runs,
    # it changes things, the configurations are what changed, and the evidence
    # is what proves all of it. Evidence sits last deliberately — it is where
    # the other views lead when an operator asks "why do you say that?", not a
    # place to start.
    NavGroup("timeline", "Timeline", "/timeline", (
        NavItem("timeline", "Overview", "/timeline"),
        NavItem("history", "Discoveries", "/history"),
        NavItem("changes", "Changes", "/changes"),
        NavItem("configuration", "Configuration", "/configuration"),
        NavItem("memory", "Evidence", "/evidence"),
    )),
    NavGroup("policy", "Policy", "/policy", (
        NavItem("policy", "Compliance", "/policy"),
    )),
    NavGroup("analyze", "Analyze", "/advisor", (
        NavItem("advisor", "Advisor", "/advisor"),
        NavItem("paths", "Investigate", "/paths"),
        NavItem("predict", "Predict", "/predict"),
        NavItem("compass", "Compass", "/compass"),
    )),
    NavGroup("setup", "Setup", "/discovery", (
        NavItem("discovery", "Discover", "/discovery"),
        NavItem("profiles", "Profiles", "/profiles"),
        NavItem("credentials", "Credentials", "/credentials"),
        NavItem("settings", "Settings", "/settings"),
    )),
)


# Every view key → the workflow that owns it. Built once, so a route keeps
# passing the same ``active`` key it always passed and the sidebar works out
# which group to open.
NAV_GROUP_FOR_ITEM: dict[str, str] = {
    item.key: group.key for group in NAV_GROUPS for item in group.items
}

# The flat view of the same navigation. This is the pre-FOCUS shape of the nav,
# preserved as a derived value so the long-standing symbol keeps working. It is
# not used to render anything — the sidebar reads NAV_GROUPS — so if a future
# reader finds no consumer, deleting this is safe.
NAV_ITEMS = tuple(
    (item.key, item.label, item.href) for group in NAV_GROUPS for item in group.items
)


def nav_group_for(active: str) -> str:
    """The workflow that owns the active view. Falls back to the view's own key
    so an unknown/one-off page never highlights the wrong workflow."""

    return NAV_GROUP_FOR_ITEM.get(active, active)


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
        "seed_cidr": getattr(profile, "seed_cidr", None),
        # What the operator actually asked for. A CIDR is expanded into
        # candidate addresses at creation, so a /24 sweep used to render as its
        # first address — "172.20.20.1" for a profile the operator created by
        # typing "172.20.20.0/24". Every screen shows this instead, so none of
        # them can disagree about what a profile's entry point is.
        "seed_label": getattr(profile, "seed_cidr", None) or profile.management_ip,
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
        "archived": bool(getattr(profile, "archived", False)),
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

    # PR-043.10 (POLISH, Part 5): a canonical device appears ONCE regardless
    # of how many observation profiles contributed evidence. Device rows are
    # collapsed by canonical hostname, and each device's interfaces are
    # unioned — Compass and Prediction target a device by name, so a
    # duplicated name in the dropdown is only noise (access1, access1,
    # access1 → access1).
    targets: list[dict[str, Any]] = []
    seen_hosts: dict[str, dict[str, Any]] = {}
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
        key = hostname.casefold()
        existing = seen_hosts.get(key)
        if existing is None:
            entry = {"hostname": hostname, "interfaces": options}
            seen_hosts[key] = entry
            targets.append(entry)
        else:
            # Merge interfaces from another observation of the same device,
            # keeping each interface name once.
            have = {option["name"].casefold() for option in existing["interfaces"]}
            for option in options:
                if option["name"].casefold() not in have:
                    existing["interfaces"].append(option)
                    have.add(option["name"].casefold())
    for entry in targets:
        entry["interfaces"].sort(key=lambda option: option["name"].casefold())
        entry["interface_names"] = ", ".join(
            option["name"] for option in entry["interfaces"]
        )
    targets.sort(key=lambda item: item["hostname"].casefold())
    return targets


def timeline_activity(
    config_events, discovery_rows, *, limit: int = 40
) -> list[dict[str, Any]]:
    """One chronology across everything Atlas remembers happening.

    Changes, Configuration, Discoveries and Evidence were four pages answering
    one question — *what changed?* This merges the two kinds of thing that
    actually occur on a timeline (a configuration changed; a discovery ran) into
    a single ordered list, so the workflow has one front door.

    Each entry carries its ``discovery_session``: the seam that links a
    configuration change back to the discovery that observed it. That link is
    what a future Change → Impact capability will follow — it is recorded here
    deliberately, and deliberately not yet followed.

    Pure aggregation over already-formed records. Sorting uses the stored UTC
    instants; only the caller renders them in the operator's zone.
    """

    from urllib.parse import quote

    entries: list[dict[str, Any]] = []
    for event in config_events:
        entries.append(
            {
                "occurred_at": event.occurred_at,
                "kind": "configuration",
                "title": f"{event.hostname} configuration changed",
                "detail": event.summary,
                "device_id": event.device_id,
                "hostname": event.hostname,
                "network": event.network,
                "severity": event.highest_severity,
                "discovery_session": event.discovery_session,
                "change_count": event.change_count,
                "href": f"/configuration/{quote(str(event.device_id), safe='')}",
            }
        )
    for row in discovery_rows:
        devices = row.get("device_count", 0)
        entries.append(
            {
                "occurred_at": row.get("started_at_iso") or "",
                "kind": "discovery",
                "title": f"Discovery ran on {row.get('profile') or 'the network'}",
                "detail": (
                    f"{devices} device(s), {row.get('relationship_count', 0)} "
                    f"relationship(s) · {row.get('network_status', 'unknown')}"
                ),
                "device_id": None,
                "hostname": None,
                "network": row.get("profile") or "",
                "severity": "low",
                "discovery_session": row.get("record_id"),
                "change_count": 0,
                # The EXACT run, not the list page: a timeline event opens
                # the record it describes.
                "href": (
                    f"/history?run={quote(str(row.get('record_id')), safe='')}"
                    if row.get("record_id") else "/history"
                ),
            }
        )
    entries.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
    return entries[:limit]


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
