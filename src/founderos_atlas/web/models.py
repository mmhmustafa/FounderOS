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
    """One view inside a workflow. ``key`` is what a route passes as ``active``.

    ``sidebar=False`` keeps a destination in the page model — breadcrumbs,
    the Pin button, the Ctrl+K palette — while omitting it from the
    rendered sidebar (PR-177). Deleting the NavItem instead would silently
    take all three.
    """

    key: str
    label: str
    href: str
    sidebar: bool = True


@dataclass(frozen=True)
class NavGroup:
    """One workflow. ``href`` is where the group link lands (its first view)."""

    key: str
    label: str
    href: str
    items: tuple[NavItem, ...]


NAV_GROUPS: tuple[NavGroup, ...] = (
    # Five primary areas (PR: calmer navigation). Item KEYS are frozen —
    # every route keeps passing the same ``active`` key it always passed
    # and every href is unchanged, so deep links, bookmarks and RBAC are
    # untouched; only the grouping above them changed.
    NavGroup("home", "Home", "/", (
        NavItem("dashboard", "Overview", "/"),
        NavItem("inbox", "Action Center", "/inbox"),
        NavItem("incidents", "Incidents", "/incidents"),
    )),
    NavGroup("network", "Network", "/topology", (
        NavItem("topology", "Topology", "/topology"),
        NavItem("configuration", "Configuration", "/configuration"),
        NavItem("memory", "Evidence", "/evidence"),
    )),
    NavGroup("operations", "Operations", "/timeline", (
        NavItem("timeline", "Timeline", "/timeline"),
        NavItem("history", "Discoveries", "/history"),
        NavItem("changes", "Changes", "/changes"),
        NavItem("policy", "Policy", "/policy"),
    )),
    NavGroup("analyze", "Analyze", "/advisor", (
        NavItem("advisor", "Advisor", "/advisor"),
        NavItem("paths", "Investigate", "/paths"),
        NavItem("predict", "Predict", "/predict"),
        NavItem("compass", "Compass", "/compass"),
        NavItem("telemetry", "Signals", "/telemetry"),
    )),
    # Administration renders last and is RBAC-filtered per item, so a
    # viewer sees only what their roles can actually open.
    NavGroup("administration", "Administration", "/discovery", (
        NavItem("discovery", "Discover", "/discovery"),
        NavItem("profiles", "Profiles", "/profiles"),
        NavItem("credentials", "Credentials", "/credentials"),
        NavItem("users", "Users", "/users"),
        NavItem("audit", "Audit", "/audit"),
        NavItem("settings", "Settings", "/settings"),
        NavItem("ai", "PRISM", "/settings/ai"),
        # The Playground is a system-admin demonstration tool, not a
        # permanent operator destination (PR-177). It keeps its key, its
        # URL, its breadcrumbs and its palette entry; its front door is
        # the card on /settings/ai.
        NavItem("prism-playground", "PRISM Playground", "/prism/playground",
                sidebar=False),
        NavItem("schedules", "Schedules", "/schedules"),
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
        "last_discovery_iso": profile.last_discovery,
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
        "owner": getattr(profile, "owner", None) or "Unassigned",
        "tags": tuple(getattr(profile, "tags", ())),
        "tags_text": ", ".join(getattr(profile, "tags", ())),
        "credential_sets": tuple(getattr(profile, "credential_sets", ())),
        "boundary_summary": (
            boundary.summary() if boundary and hasattr(boundary, "summary")
            else (
                f"{len(boundary.include_cidrs)} include / "
                f"{len(boundary.exclude_cidrs)} exclude"
                if boundary else "Unrestricted"
            )
        ),
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
                        "created_at": format_timestamp(getattr(entry, "created_at", None)),
                        "last_used": format_timestamp(getattr(entry, "last_used", None)),
                        "last_failure": format_timestamp(getattr(entry, "last_failure", None)),
                        "rotation_due_at": format_timestamp(getattr(entry, "rotation_due_at", None)),
                        "expires_at": format_timestamp(getattr(entry, "expires_at", None)),
                        "last_test_status": getattr(entry, "last_test_status", None) or "not tested",
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


def allowed_nav_path(app, path: str) -> bool:
    """Whether the CURRENT request's principal may open ``path``.

    The nav and the command palette share this ONE predicate (PR-172
    review) — two filters once disagreed, and the unfiltered one won:
    the palette listed administration pages the nav correctly hid.

    Display fails open (an unresolvable path stays visible); access
    stays closed — RBAC is enforced on every request regardless.
    """

    from flask import g

    from .authz_map import PUBLIC, permission_for_endpoint

    principal = getattr(g, "principal", None)
    if principal is None:
        return True

    cache = app.extensions.setdefault("atlas_nav_endpoints", {})
    bare = path.split("?", 1)[0].split("#", 1)[0]
    if bare not in cache:
        try:
            cache[bare] = app.url_map.bind("nav.localhost").match(
                bare, method="GET"
            )[0]
        except Exception:  # noqa: BLE001 - display fails open
            cache[bare] = None
    endpoint = cache[bare]
    if endpoint is None:
        return True
    permission = permission_for_endpoint(endpoint)
    if permission == PUBLIC or permission is None:
        return True
    return permission in principal.permissions


def visible_nav_groups(app) -> tuple[NavGroup, ...]:
    """NAV_GROUPS filtered to what the CURRENT request's principal can
    open. The one builder both the context processor and base_context
    use — two copies once disagreed, and the unfiltered one won.
    """

    from dataclasses import replace as _dc_replace

    groups = []
    for group in NAV_GROUPS:
        items = tuple(
            item for item in group.items
            if allowed_nav_path(app, item.href)
        )
        if items:
            groups.append(_dc_replace(group, items=items))
    return tuple(groups)


# -- Progressive first-run navigation (PR-177) --------------------------------
#
# Before the workspace holds a usable discovery, the sidebar shows only
# what a new operator can meaningfully act on. This is GUIDANCE layered
# over RBAC, never access control: every route stays reachable, RBAC
# stays the only authorization mechanism, and the Ctrl+K palette keeps
# the full RBAC-visible page list so a hidden page is always findable.

# Item KEYS (frozen by contract, see NAV_GROUPS) visible before the
# first usable discovery. The set spans two groups — `dashboard` lives
# in `home`; `discovery` and `settings` in `administration` — so the
# filter is item-level and `guided_nav_groups` drops the emptied
# Network/Operations/Analyze groups for free.
PRE_DISCOVERY_ITEM_KEYS = frozenset({"dashboard", "discovery", "settings"})


def _nav_reveal_marker(app) -> Path:
    """The durable per-workspace reveal marker.

    It exists for exactly one case: an already-operational workspace
    must not silently re-enter first-run guidance because its only
    discovery profile was later deleted or archived (the scope's data
    stays on disk, but ``profile_scopes`` no longer names it). It lives
    in the OUTPUT directory, which the backup manifest deliberately
    does not carry — so a workspace restored onto a clean machine
    correctly starts in first-run guidance.
    """

    return Path(app.config["ATLAS_OUTPUT_DIR"]) / ".atlas" / "nav-revealed"


def mark_nav_revealed(app) -> None:
    """Latch the reveal for this process and this workspace, best effort.

    Called on a computed positive answer and by the discovery job
    manager's success hook — both moments where usable artifacts are
    already on disk. Never called from a fail-open path.
    """

    app.extensions["atlas_nav_revealed"] = True
    try:
        marker = _nav_reveal_marker(app)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
    except OSError:
        # The in-process latch still holds; the marker is a durability
        # nicety, not a source of truth.
        app.logger.debug("could not write the nav-revealed marker",
                         exc_info=True)


def workspace_has_discovery(app) -> bool:
    """Whether this workspace holds a usable discovery (PR-177).

    The authoritative signal is the one Home already trusts:
    ``active_scopes`` over ``DiscoveryScope.has_data()`` — a topology
    snapshot or a discovery-history directory. A failed run writes
    neither, so it never reveals; a partial run writes both, so it does.

    Contract: A POSITIVE ANSWER IS NEVER INVALIDATED WITHIN A PROCESS;
    A NEGATIVE ANSWER IS NEVER CACHED BEYOND ITS STAMP. The evaluation
    order is load-bearing:

      0. A principal without the discovery-run permission is never
         guided — they could do nothing to leave SETUP, so for them the
         answer is always "revealed".
      1. The monotone in-process latch (only ever assigned True).
      2. The per-request memo.
      3. The durable marker file (one ``is_file``).
      4. Short-circuit: no default-scope data and no profile-scopes
         directory means no scope can possibly hold data.
      5. A stamp-keyed negative memo — a workspace whose runs all fail
         has a profile-scopes directory, and without this it would pay
         a profiles.json parse on every render, forever.
      6. The live filesystem signal.

    Display fails open (the `allowed_nav_path` doctrine): any
    unexpected error logs at debug and answers True WITHOUT writing the
    latch, the marker, or any memo — a transient error must never
    permanently reveal, and must never hide working navigation.
    """

    from flask import g

    from founderos_atlas.access.models import DISCOVERY_RUN

    try:
        principal = getattr(g, "principal", None)
        if principal is not None and DISCOVERY_RUN not in principal.permissions:
            return True
        if app.extensions.get("atlas_nav_revealed"):
            return True
        cached = getattr(g, "_atlas_nav_revealed", None)
        if cached is not None:
            return cached
        if _nav_reveal_marker(app).is_file():
            app.extensions["atlas_nav_revealed"] = True
            g._atlas_nav_revealed = True
            return True

        out = Path(app.config["ATLAS_OUTPUT_DIR"])
        history_root = Path(app.config["ATLAS_HISTORY_ROOT"])
        profiles_dir = out / ".atlas" / "profiles"

        from founderos_atlas.workspace.scopes import (
            active_scopes,
            default_scope,
            profile_scopes,
        )

        base = default_scope(out, history_root)
        if not base.has_data() and not profiles_dir.is_dir():
            g._atlas_nav_revealed = False
            return False

        stamp = _nav_signal_stamp(app, profiles_dir)
        memo = app.extensions.get("atlas_nav_stamp")
        if memo is not None and memo == stamp:
            g._atlas_nav_revealed = False
            return False

        profiles = app.config["ATLAS_PROFILE_SERVICE"].list_profiles()
        revealed = bool(
            active_scopes(base, profile_scopes(out, profiles))
        )
        if revealed:
            mark_nav_revealed(app)
        else:
            app.extensions["atlas_nav_stamp"] = stamp
        g._atlas_nav_revealed = revealed
        return revealed
    except Exception:  # noqa: BLE001 - display fails open, never caches
        # Broad on purpose: ProfileRepository raises
        # WorkspaceCorruptedError (an AtlasWorkspaceError, not OSError/
        # ValueError), and this runs from a context processor that also
        # fires on 404/500 pages — it must never raise, and it must
        # never latch a fail-open answer.
        app.logger.debug("nav readiness probe failed open", exc_info=True)
        return True


def _nav_signal_stamp(app, profiles_dir: Path) -> tuple:
    """A cheap stamp that changes whenever a negative answer could.

    New/edited profiles rewrite ``profiles.json``; a first artifact for
    a scope creates its directory under the profile-scopes root (bumping
    the root's mtime); and a successful WEB run flips the in-process
    latch via the job manager's success hook before this memo is ever
    consulted again.
    """

    profiles_json = (
        Path(app.config["ATLAS_WORKSPACE_ROOT"]) / "profiles.json"
    )
    parts: list = []
    for path in (profiles_json, profiles_dir):
        try:
            stat = path.stat()
            parts.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append(None)
    return tuple(parts)


def guided_nav_groups(
    groups: tuple[NavGroup, ...], *, revealed: bool
) -> tuple[NavGroup, ...]:
    """The contextual guidance filter (PR-177). Pure: tuple in, tuple out.

    Always drops ``sidebar=False`` items; before the reveal also drops
    items outside ``PRE_DISCOVERY_ITEM_KEYS``. Groups left empty
    disappear, exactly as `visible_nav_groups` already does for RBAC.
    Composes OVER the RBAC filter — it can only ever narrow what RBAC
    allowed, never widen it.
    """

    from dataclasses import replace as _dc_replace

    filtered = []
    for group in groups:
        items = tuple(
            item for item in group.items
            if item.sidebar
            and (revealed or item.key in PRE_DISCOVERY_ITEM_KEYS)
        )
        if items:
            filtered.append(_dc_replace(group, items=items))
    return tuple(filtered)


def render_nav_groups(app) -> tuple[NavGroup, ...]:
    """The ONE builder both sidebar render sites use (PR-177).

    RBAC first, guidance second. The Ctrl+K pages filter deliberately
    keeps calling `visible_nav_groups` directly — search follows access,
    not guidance, so a hidden-but-permitted page stays findable.
    """

    return guided_nav_groups(
        visible_nav_groups(app), revealed=workspace_has_discovery(app)
    )
