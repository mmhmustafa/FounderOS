"""Build search entries from deterministic evidence.

Two layers:

- ``entries_from_graph``      — canonical devices, interfaces, sites, and
                                topology links from the Enterprise Graph
                                (UNITY). Pure; no disk access.
- ``entries_from_workspace``  — everything the workspace's artifacts add:
                                profiles, credential NAMES, the latest
                                predictions, investigation history, change
                                summaries, and discovery-run history per
                                profile scope.

VLAN evidence honesty: Atlas indexes VLAN ids through discovered SVI
interfaces (``Vlan20``) — the only VLAN evidence collected today. VRFs
are not collected yet, so no VRF entry can honestly exist.
"""

from __future__ import annotations

import json
from pathlib import Path

from founderos_atlas.federation import EnterpriseGraph
from founderos_atlas.history import HistoryRepository
from founderos_atlas.workspace import profile_scope

from .models import SearchEntry, SearchKey


HISTORY_RUNS_PER_SCOPE = 3
INVESTIGATIONS_PER_SCOPE = 10

# Deterministic IOS-style abbreviations (longest prefix wins), so the
# short form engineers type ("Gi0/1") finds the canonical interface.
_INTERFACE_ABBREVIATIONS = (
    ("twentyfivegigabitethernet", "Twe"),
    ("hundredgigabitethernet", "Hu"),
    ("fortygigabitethernet", "Fo"),
    ("tengigabitethernet", "Te"),
    ("gigabitethernet", "Gi"),
    ("fastethernet", "Fa"),
    ("port-channel", "Po"),
    ("loopback", "Lo"),
    ("tunnel", "Tu"),
)


def interface_alias(name: str) -> str | None:
    """The short CLI form of a canonical interface name, when one exists."""

    folded = name.casefold()
    for prefix, short in _INTERFACE_ABBREVIATIONS:
        if folded.startswith(prefix):
            return f"{short}{name[len(prefix):]}"
    return None


def entries_from_graph(
    graph: EnterpriseGraph,
    *,
    health_by_profile: dict[str, int] | None = None,
) -> tuple[SearchEntry, ...]:
    """Canonical devices, interfaces, sites, and links — evidence only."""

    health_by_profile = health_by_profile or {}
    entries: list[SearchEntry] = []
    neighbor_by_port: dict[tuple[str, str], str] = {}
    for link in graph.links:
        if link.local_interface:
            neighbor_by_port[
                (link.local_hostname.casefold(), link.local_interface.casefold())
            ] = link.remote_hostname
        if link.remote_interface and not link.is_boundary:
            neighbor_by_port[
                (link.remote_hostname.casefold(), link.remote_interface.casefold())
            ] = link.local_hostname

    site_devices: dict[str, int] = {}
    for device in graph.devices:
        site_devices[device.site.label] = site_devices.get(device.site.label, 0) + 1
        decision = graph.decision_for(device.enterprise_id)
        health = None
        if len(device.profile_names) == 1:
            health = health_by_profile.get(device.profile_names[0])
        last_seen = max(
            (
                observation.observed_at
                for observation in device.observations
                if observation.observed_at
            ),
            default=None,
        )
        keys = [SearchKey("hostname", device.hostname)]
        keys.extend(
            SearchKey("alias", alias, canonical=True) for alias in device.aliases
        )
        keys.extend(
            SearchKey("management ip", ip) for ip in device.management_ips
        )
        if device.serial_number:
            keys.append(
                SearchKey("serial number", device.serial_number, canonical=True)
            )
        keys.append(
            SearchKey("enterprise id", device.enterprise_id, canonical=True)
        )
        if device.platform:
            keys.append(SearchKey("platform", device.platform))
        if device.os_version:
            keys.append(SearchKey("operating system", device.os_version))
        if device.site.label:
            keys.append(SearchKey("site", device.site.label))
        entries.append(
            SearchEntry(
                group="devices",
                title=device.hostname,
                subtitle=", ".join(device.management_ips) or "no management address",
                href=f"/devices/{device.enterprise_id}",
                keys=tuple(keys),
                detail={
                    "management_ips": list(device.management_ips),
                    "platform": device.platform or "—",
                    "site": device.site.label,
                    "health": health,
                    "last_seen": last_seen,
                    "observation_count": len(device.observations),
                    "confidence_percent": (
                        decision.confidence_percent if decision else None
                    ),
                    "confidence_band": (
                        decision.confidence_band if decision else None
                    ),
                    "observed_by": list(device.profile_names),
                },
            )
        )
        for interface in graph.interfaces.get(device.enterprise_id, ()):
            neighbor = neighbor_by_port.get(
                (device.hostname.casefold(), interface.name.casefold())
            )
            interface_keys = [
                SearchKey("interface", interface.name),
                # Found through its parent's name: real, but one rank behind
                # the device itself so exact devices outrank their interfaces.
                SearchKey(
                    "device", f"{device.hostname} {interface.name}",
                    secondary=True,
                ),
            ]
            alias = interface_alias(interface.name)
            if alias:
                interface_keys.append(
                    SearchKey("interface alias", alias, canonical=True)
                )
            if interface.name.casefold().startswith("vlan"):
                # The discovered SVI is Atlas's VLAN evidence.
                interface_keys.append(
                    SearchKey("vlan", f"VLAN{interface.name[4:].strip()}")
                )
            if interface.ip_address:
                interface_keys.append(
                    SearchKey("interface ip", interface.ip_address)
                )
            if interface.description:
                interface_keys.append(
                    SearchKey("description", interface.description)
                )
            entries.append(
                SearchEntry(
                    group="interfaces",
                    title=f"{device.hostname} {interface.name}",
                    subtitle=_interface_state(interface),
                    href=f"/devices/{device.enterprise_id}#interfaces",
                    keys=tuple(interface_keys),
                    detail={
                        "device": device.hostname,
                        "interface": interface.name,
                        "status": interface.status or "unknown",
                        "protocol_status": interface.protocol_status or "unknown",
                        "description": interface.description,
                        "neighbor": neighbor,
                        "observed_by": list(interface.observed_by),
                    },
                )
            )

    for site, count in sorted(site_devices.items()):
        entries.append(
            SearchEntry(
                group="sites",
                title=site,
                subtitle=f"{count} device(s)",
                href=f"/topology?scope=all&site={site}",
                keys=(SearchKey("site", site),),
                detail={"device_count": count},
            )
        )

    # Address ownership: an "unknown boundary" whose far end is an address a
    # canonical device owns is not unknown — normalized evidence resolves it,
    # and the search result says so instead of crying boundary.
    owned_addresses: dict[str, str] = {}
    for device in graph.devices:
        for address in device.management_ips:
            owned_addresses.setdefault(str(address).strip(), device.hostname)
    for enterprise_id, interfaces in graph.interfaces.items():
        owner_device = graph.device_by_id(enterprise_id)
        owner = owner_device.hostname if owner_device else None
        if not owner:
            continue
        for interface in interfaces:
            raw = str(getattr(interface, "ip_address", "") or "").strip()
            address = raw.partition("/")[0]
            if address:
                owned_addresses.setdefault(address, owner)

    for link in graph.links:
        left = f"{link.local_hostname} {link.local_interface or '?'}"
        right = f"{link.remote_hostname} {link.remote_interface or '?'}"
        resolved_owner = (
            owned_addresses.get(str(link.remote_hostname).strip())
            if link.is_boundary else None
        )
        subtitle = (
            (f"resolves to {resolved_owner} (address ownership)"
             if resolved_owner else "unknown boundary")
            if link.is_boundary
            else ("cross-profile link" if link.cross_profile else "link")
        )
        entries.append(
            SearchEntry(
                group="topology",
                title=f"{left} ↔ {right}",
                subtitle=subtitle,
                href="/topology?scope=all",
                keys=(
                    SearchKey("device", link.local_hostname),
                    SearchKey("device", link.remote_hostname),
                    SearchKey("interface", link.local_interface or ""),
                    SearchKey("interface", link.remote_interface or ""),
                    SearchKey("protocol", link.protocol),
                ),
                detail={
                    "observed_by": list(link.observed_by),
                    "cross_profile": link.cross_profile,
                    "boundary": link.is_boundary,
                },
            )
        )
    return tuple(entries)


def entries_from_workspace(
    base_output_dir: str | Path,
    profiles,
    *,
    credential_sets=(),
) -> tuple[SearchEntry, ...]:
    """Profiles, credential names, and per-scope report/history entries."""

    entries: list[SearchEntry] = []
    for profile in profiles:
        keys = [
            SearchKey("profile", profile.name),
            SearchKey("profile id", profile.profile_id, canonical=True),
        ]
        keys.extend(
            SearchKey("seed", str(seed))
            for seed in getattr(profile, "all_seeds", ()) or ()
        )
        entries.append(
            SearchEntry(
                group="profiles",
                title=profile.name,
                subtitle="discovery profile",
                href=f"/?scope={profile.profile_id}",
                keys=tuple(keys),
                detail={"profile_id": profile.profile_id},
            )
        )
        scope = profile_scope(base_output_dir, profile.profile_id, profile.name)
        entries.extend(
            _scope_report_entries(
                scope.output_dir, scope.scope_id, profile.name, scope.history_root
            )
        )

    # The enterprise scope's own reports (enterprise predictions and
    # cross-profile investigations, PR-037A) are evidence too.
    entries.extend(
        _scope_report_entries(
            Path(base_output_dir) / ".atlas" / "enterprise",
            "all",
            "Enterprise",
            None,
        )
    )

    # Compass maintenance plans (PR-039): searchable by title, CAB
    # reference, engineer, and every device inside the plan.
    entries.extend(_plan_entries(base_output_dir))

    for credential_set in credential_sets:
        # Names only — never usernames, never secrets.
        keys = [SearchKey("credential set", credential_set.name)]
        keys.extend(
            SearchKey("credential entry", entry.label)
            for entry in getattr(credential_set, "entries", ())
            if getattr(entry, "label", None)
        )
        entries.append(
            SearchEntry(
                group="credentials",
                title=credential_set.name,
                subtitle=f"{len(getattr(credential_set, 'entries', ()))} entry(ies)",
                href="/credentials",
                keys=tuple(keys),
                detail={},
            )
        )
    return tuple(entries)


# -- per-scope report and history entries ---------------------------------------


def _scope_report_entries(
    output_dir: Path, scope_id: str, label: str, history_root: Path | None
) -> list[SearchEntry]:
    entries: list[SearchEntry] = []
    prediction = _read_json(output_dir / "prediction_report.json")
    if isinstance(prediction, dict):
        request = prediction.get("change_request") or {}
        subject = (
            f"{request.get('target_device') or '?'} "
            f"{request.get('target_object') or ''}"
        ).strip()
        risk = (prediction.get("risk") or {}).get("level") or "unknown"
        entries.append(
            SearchEntry(
                group="predictions",
                title=f"Prediction — {request.get('change_type') or '?'} {subject}",
                subtitle=f"{label} · risk {risk}",
                href=f"/predict?scope={scope_id}",
                keys=(
                    SearchKey("keyword", "prediction"),
                    SearchKey("device", str(request.get("target_device") or "")),
                    SearchKey("interface", str(request.get("target_object") or "")),
                    SearchKey("risk", str(risk)),
                    SearchKey("network", label),
                ),
                detail={"risk": risk, "network": label},
                historical=True,
            )
        )
    investigations = _read_json(output_dir / "path_investigations.json")
    if isinstance(investigations, list):
        for item in investigations[:INVESTIGATIONS_PER_SCOPE]:
            if not isinstance(item, dict):
                continue
            entries.append(
                SearchEntry(
                    group="investigations",
                    title=(
                        f"Investigation — {item.get('source')} → "
                        f"{item.get('destination')} ({item.get('status')})"
                    ),
                    subtitle=f"{label} · {item.get('generated_at') or ''}".strip(" ·"),
                    href=f"/paths?scope={scope_id}",
                    keys=(
                        SearchKey("keyword", "investigation"),
                        SearchKey("keyword", "recent"),
                        SearchKey("device", str(item.get("source") or "")),
                        SearchKey("device", str(item.get("destination") or "")),
                        SearchKey("status", str(item.get("status") or "")),
                        SearchKey("network", label),
                    ),
                    detail={
                        "status": item.get("status"),
                        "confidence_percent": item.get("confidence_percent"),
                        "network": label,
                    },
                    historical=True,
                )
            )
    changes = _read_json(output_dir / "state_change_report.json")
    if isinstance(changes, dict) and changes.get("change_count"):
        entries.append(
            SearchEntry(
                group="changes",
                title=(
                    f"Operational changes — {label}: "
                    f"{changes.get('change_count')} change(s)"
                ),
                subtitle=f"{changes.get('active_issue_count') or 0} active issue(s)",
                href=f"/changes?scope={scope_id}",
                keys=(
                    SearchKey("keyword", "changes"),
                    SearchKey("keyword", "recent"),
                    SearchKey("network", label),
                ),
                detail={"change_count": changes.get("change_count")},
                historical=True,
            )
        )
    if history_root is None:
        return entries
    for record in HistoryRepository(history_root).load().records[
        :HISTORY_RUNS_PER_SCOPE
    ]:
        entries.append(
            SearchEntry(
                group="history",
                title=f"Discovery run — {label} · {record.completed_at}",
                subtitle=f"{record.device_count} device(s)",
                href=f"/history?scope={scope_id}",
                keys=(
                    SearchKey("keyword", "history"),
                    SearchKey("keyword", "discovery"),
                    SearchKey("keyword", "recent"),
                    SearchKey("run id", record.record_id, canonical=True),
                    SearchKey("network", label),
                ),
                detail={
                    "device_count": record.device_count,
                    "completed_at": record.completed_at,
                },
                historical=True,
            )
        )
    return entries


def _plan_entries(base_output_dir: str | Path) -> list[SearchEntry]:
    from founderos_atlas.compass import PlanRepository

    entries: list[SearchEntry] = []
    for plan in PlanRepository(base_output_dir).list_plans():
        keys = [
            SearchKey("plan title", plan.title),
            SearchKey("plan id", plan.plan_id, canonical=True),
            SearchKey("keyword", "plan"),
            SearchKey("keyword", "maintenance"),
        ]
        if plan.cab_reference:
            keys.append(SearchKey("cab reference", plan.cab_reference, canonical=True))
        if plan.engineer:
            keys.append(SearchKey("engineer", plan.engineer))
        for change in plan.changes:
            keys.append(SearchKey("device", change.device))
        entries.append(
            SearchEntry(
                group="plans",
                title=plan.title,
                subtitle=(
                    f"{plan.status} · {len(plan.changes)} change(s)"
                    + (f" · {plan.maintenance_window}" if plan.maintenance_window else "")
                ),
                href=f"/compass/{plan.plan_id}",
                keys=tuple(keys),
                detail={
                    "status": plan.status,
                    "engineer": plan.engineer,
                    "cab_reference": plan.cab_reference,
                    "change_count": len(plan.changes),
                },
            )
        )
    return entries


def health_by_profile_from_scopes(base_output_dir: str | Path, profiles) -> dict[str, int]:
    """Each profile's latest network health score, when its scope has one."""

    scores: dict[str, int] = {}
    for profile in profiles:
        scope = profile_scope(base_output_dir, profile.profile_id, profile.name)
        report = _read_json(scope.output_dir / "intelligence_report.json")
        if not isinstance(report, dict):
            continue
        score = (report.get("health") or {}).get("score")
        if isinstance(score, (int, float)):
            scores[profile.name] = int(score)
    return scores


def _interface_state(interface) -> str:
    status = interface.status or "unknown"
    protocol = interface.protocol_status or "unknown"
    return f"{status}/{protocol}"


def _read_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def entries_from_operational(
    base_output_dir: str | Path, profiles
) -> tuple[SearchEntry, ...]:
    """Policies (and their failures), evidence records, configuration
    histories, and incident reports — the operational layer of search.

    Everything is read from stored metadata (never a blob), each entry
    carries its scope in the href, and identity confidence is never
    mixed into relevance: it travels in ``detail`` for display only.
    """

    from urllib.parse import quote

    entries: list[SearchEntry] = []

    # The installed policy pack: policies are addressable objects.
    try:
        from founderos_atlas.policy import list_packs

        for pack in list_packs():
            for policy in pack.policies:
                entries.append(
                    SearchEntry(
                        group="policies",
                        title=policy.name,
                        subtitle=(
                            f"{policy.category} · severity {policy.severity}"
                        ),
                        href=f"/policy?scope=all#policy-{quote(policy.policy_id, safe='')}",
                        keys=(
                            SearchKey("policy", policy.name),
                            SearchKey("policy id", policy.policy_id, canonical=True),
                            SearchKey("category", policy.category),
                        ),
                        detail={"pack": pack.name, "severity": policy.severity},
                    )
                )
    except Exception:  # noqa: BLE001 - packs are optional evidence
        pass

    for profile in profiles:
        scope = profile_scope(base_output_dir, profile.profile_id, profile.name)
        scope_query = quote(profile.profile_id, safe="")

        # Incident report of the scope.
        report = _read_json(scope.output_dir / "incident_report.json")
        if isinstance(report, dict) and report.get("title"):
            affected = [str(item) for item in report.get("affected_devices") or ()]
            entries.append(
                SearchEntry(
                    group="incidents",
                    title=str(report["title"]),
                    subtitle=(
                        f"{str(report.get('confidence') or 'unknown')} confidence"
                        + (f" · {len(affected)} affected" if affected else "")
                    ),
                    href=f"/incidents?scope={scope_query}",
                    keys=tuple(
                        [SearchKey("incident", str(report["title"]))]
                        + [SearchKey("device", name, secondary=True)
                           for name in affected]
                    ),
                    detail={
                        "network": profile.name,
                        "generated_at": report.get("generated_at"),
                    },
                )
            )

        # Evidence records + configuration histories + policy failures live
        # in Enterprise Memory. Metadata only — listings never read a blob.
        store_dir = scope.output_dir / "enterprise-memory"
        if not store_dir.is_dir():
            continue
        try:
            from founderos_atlas.enterprise_memory import (
                EnterpriseMemory,
                EnterpriseMemoryStore,
            )

            store = EnterpriseMemoryStore(store_dir)
            memory = EnterpriseMemory(store)
        except Exception:  # noqa: BLE001 - memory is optional evidence
            continue

        try:
            for record in store.evidence_records():
                if not record.content_sha256:
                    continue
                entries.append(
                    SearchEntry(
                        group="evidence",
                        title=f"{record.hostname} · {record.command}",
                        subtitle=(
                            f"{record.source} · {record.collection_status} · "
                            f"session {record.discovery_session}"
                        ),
                        href=(
                            f"/evidence/device/{quote(record.device_id, safe='')}"
                            f"/record/{quote(record.content_sha256, safe='')}"
                            f"?scope={scope_query}"
                        ),
                        keys=(
                            SearchKey("device", record.hostname),
                            SearchKey("command", record.command),
                            SearchKey(
                                "content hash", record.content_sha256,
                                canonical=True,
                            ),
                        ),
                        detail={
                            "network": profile.name,
                            "collected_at": record.collected_at,
                        },
                    )
                )
        except Exception:  # noqa: BLE001
            pass

        try:
            # Configuration histories come from Configuration Memory — the
            # SAME store the /configuration pages read, so a search hit can
            # never land on an empty page.
            from founderos_atlas.config_memory import ConfigMemoryStore

            config_store = ConfigMemoryStore(
                scope.output_dir / "config-memory"
            )
            for history in config_store.histories():
                entries.append(
                    SearchEntry(
                        group="configurations",
                        title=f"{history.hostname} configuration",
                        subtitle=(
                            f"{len(history.versions)} version(s) · "
                            f"{history.network or profile.name}"
                        ),
                        href=(
                            f"/configuration/{quote(history.device_id, safe='')}"
                            f"?scope={scope_query}"
                        ),
                        keys=(
                            SearchKey("device", history.hostname),
                            SearchKey(
                                "device id", history.device_id, canonical=True
                            ),
                            SearchKey("configuration", "configuration",
                                      secondary=True),
                        ),
                        detail={"network": history.network or profile.name},
                    )
                )
        except Exception:  # noqa: BLE001
            pass

        try:
            from founderos_atlas.policy import PolicyEngine

            report = PolicyEngine().evaluate_scopes(
                [(profile.name, memory)], scope_label=profile.name
            )
            for evaluation in report.evaluations:
                if evaluation.status not in ("fail", "warning"):
                    continue
                entries.append(
                    SearchEntry(
                        group="policies",
                        title=(
                            f"{evaluation.policy.name} — {evaluation.hostname}"
                        ),
                        subtitle=(
                            f"{evaluation.status_label} · "
                            f"{evaluation.policy.category} · {profile.name}"
                        ),
                        href=(
                            f"/policy?scope={scope_query}"
                            f"&device={quote(evaluation.hostname, safe='')}"
                            f"#result-{quote(evaluation.policy.policy_id, safe='')}"
                            f"-{quote(evaluation.hostname, safe='')}"
                        ),
                        keys=(
                            SearchKey("policy", evaluation.policy.name),
                            SearchKey("device", evaluation.hostname),
                            SearchKey("status", evaluation.status_label,
                                      secondary=True),
                        ),
                        detail={
                            "network": profile.name,
                            "status": evaluation.status,
                        },
                    )
                )
        except Exception:  # noqa: BLE001
            pass

    return tuple(entries)
