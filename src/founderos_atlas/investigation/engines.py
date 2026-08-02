"""Investigation engines (PR-167, Part 4).

Each function is one step an investigation can execute. They read
evidence Atlas has already collected — the federated graph, per-device
routing evidence, interfaces, links, change history — and write
findings, gaps and citations into the shared context.

Two rules hold everywhere:

* An engine reports what the evidence says, and says what the evidence
  does not contain. Atlas collects BGP *summary* output, so it knows
  session state, peer, AS and accepted prefixes — and does NOT know
  advertised prefixes, uptime or last flap. Where a question implies
  those, the gap is stated rather than glossed.
* Nothing here re-runs discovery or touches a device. Investigations
  are reads over stored evidence (Part 12).
"""

from __future__ import annotations

from typing import Any

from .models import InvestigationContext


def _device_metadata(graph) -> dict[str, Any]:
    attributes = getattr(graph, "attributes", None) or {}
    return attributes.get("device_metadata") or {}


def routing_evidence_for(graph, device_id: str) -> dict[str, Any]:
    """One device's stored routing evidence, or an empty shape."""

    metadata = _device_metadata(graph).get(device_id) or {}
    evidence = metadata.get("routing_evidence") or {}
    return {
        "bgp_sessions": list(evidence.get("bgp_sessions") or ()),
        "ospf_adjacencies": list(evidence.get("ospf_adjacencies") or ()),
    }


def device_by_id(graph, device_id: str):
    getter = getattr(graph, "device_by_id", None)
    if callable(getter):
        return getter(device_id)
    for device in getattr(graph, "devices", ()):
        if str(device.enterprise_id) == device_id:
            return device
    return None


def _addresses_of(graph, device_ids) -> set[str]:
    """Every address Atlas associates with a set of devices: management
    addresses, interface addresses and BGP router ids. This is what
    lets a peer address be recognised as 'the other site'."""

    found: set[str] = set()
    interfaces = getattr(graph, "interfaces", {}) or {}
    for device_id in device_ids:
        device = device_by_id(graph, device_id)
        if device is None:
            continue
        for address in getattr(device, "management_ips", ()) or ():
            if address:
                found.add(str(address).split("/")[0])
        for interface in interfaces.get(device_id, ()) or ():
            address = getattr(interface, "ip_address", "")
            if address:
                found.add(str(address).split("/")[0])
        for session in routing_evidence_for(graph, device_id)["bgp_sessions"]:
            router_id = session.get("router_id")
            if router_id:
                found.add(str(router_id))
    return found


# -- engine: sites and devices ---------------------------------------------

def locate_entities(context: InvestigationContext) -> bool:
    """Confirm what the question named, and put devices in scope."""

    entities = context.entities
    resolved = [item for item in entities.all() if item.ok]
    if not resolved:
        return False
    for entity in resolved:
        if entity.kind == "site":
            context.add_finding(
                f"Site {entity.label}",
                f"{len(entity.device_ids)} device(s) assigned",
                href="/topology", engine="graph",
            )
        elif entity.kind == "name-group":
            context.add_finding(
                f"Scope {entity.label}",
                f"{len(entity.device_ids)} device(s) matched by hostname",
                href="/topology", engine="graph",
            )
            # The weaker basis travels with the answer, every time.
            context.add_gap(entity.detail)
        else:
            context.add_finding(
                f"Device {entity.label}", entity.detail or "resolved",
                href=f"/devices/{entity.identifier}", engine="graph",
            )
    context.cite(
        "Enterprise Graph",
        f"{len(getattr(context.graph, 'devices', ()) or ())} managed "
        "device(s) in the federated snapshot",
        "/topology?scope=all",
    )
    return True


# -- engine: BGP -----------------------------------------------------------

_ESTABLISHED = ("established", "estab", "up")

# The same sentence wherever BGP is reported: the limits of the
# evidence do not depend on which question asked for it.
BGP_EVIDENCE_LIMIT = (
    "Atlas collects BGP summary output: it records session state, peer, "
    "AS numbers and accepted prefixes. Advertised prefix counts, session "
    "uptime and last-flap times are not in that output, so Atlas cannot "
    "report them."
)


def _session_is_established(session: dict[str, Any]) -> bool:
    return str(session.get("state") or "").casefold() in _ESTABLISHED


def bgp_between(context: InvestigationContext) -> bool:
    """BGP between two resolved endpoints — the flagship case.

    Sessions on the source's devices whose peer address belongs to the
    destination are the peering between those endpoints. Everything
    reported is a stored observation; nothing is inferred.
    """

    graph = context.graph
    source = context.entities.source
    destination = context.entities.destination
    if not (source and source.ok and destination and destination.ok):
        return False

    far_addresses = _addresses_of(graph, destination.device_ids)
    near_addresses = _addresses_of(graph, source.device_ids)
    matched: list[tuple[str, dict[str, Any]]] = []
    total_sessions = 0
    for device_id in source.device_ids:
        for session in routing_evidence_for(graph, device_id)["bgp_sessions"]:
            total_sessions += 1
            peer = str(session.get("peer_address") or "").split("/")[0]
            if peer and peer in far_addresses:
                matched.append((device_id, session))
    # The reverse direction: sessions on the destination pointing back.
    for device_id in destination.device_ids:
        for session in routing_evidence_for(graph, device_id)["bgp_sessions"]:
            peer = str(session.get("peer_address") or "").split("/")[0]
            if peer and peer in near_addresses:
                pair = (device_id, session)
                if pair not in matched:
                    matched.append(pair)

    context.facts["bgp_sessions_total"] = total_sessions
    context.facts["bgp_sessions_between"] = len(matched)

    if not matched:
        if total_sessions == 0:
            context.add_gap(
                f"Atlas holds no BGP evidence for {source.label} — no "
                "device there reported a BGP summary at the last "
                "discovery."
            )
        else:
            context.add_gap(
                f"Atlas found {total_sessions} BGP session(s) at "
                f"{source.label}, but none of them peers with an address "
                f"belonging to {destination.label}. On this evidence "
                "there is no BGP peering between these two."
            )
        return True

    established = [item for item in matched if _session_is_established(item[1])]
    for device_id, session in matched:
        device = device_by_id(graph, device_id)
        hostname = getattr(device, "hostname", device_id)
        state = str(session.get("state") or "unknown")
        remote_as = session.get("remote_as") or "unknown AS"
        local_as = session.get("local_as") or "unknown AS"
        prefixes = session.get("accepted_prefixes")
        detail = (
            f"peer {session.get('peer_address')} "
            f"(AS {local_as} → AS {remote_as}), state {state}"
        )
        if prefixes is not None:
            detail += f", {prefixes} prefix(es) accepted"
        vrf = session.get("vrf")
        if vrf and vrf != "default":
            detail += f", VRF {vrf}"
        context.add_finding(
            f"BGP {hostname}", detail,
            href=f"/devices/{device_id}", engine="routing",
        )
        context.cite(
            "BGP Observations",
            f"{hostname}: {session.get('source_command') or 'BGP summary'}",
            f"/devices/{device_id}",
        )

    context.facts["bgp_established"] = len(established)
    context.add_gap(BGP_EVIDENCE_LIMIT)   # always, wherever BGP is read
    return True


def bgp_for_devices(context: InvestigationContext) -> bool:
    """BGP for whatever devices are in scope (no second endpoint)."""

    graph = context.graph
    if not context.device_ids:
        return False
    sessions: list[tuple[str, dict[str, Any]]] = []
    for device_id in context.device_ids:
        for session in routing_evidence_for(graph, device_id)["bgp_sessions"]:
            sessions.append((device_id, session))
    context.facts["bgp_sessions_total"] = len(sessions)
    if not sessions:
        context.add_gap(
            "No device in scope reported a BGP summary at the last "
            "discovery, so Atlas holds no BGP evidence for it."
        )
        return True
    established = [item for item in sessions if _session_is_established(item[1])]
    context.facts["bgp_established"] = len(established)
    for device_id, session in sessions[:12]:
        device = device_by_id(graph, device_id)
        hostname = getattr(device, "hostname", device_id)
        detail = (
            f"peer {session.get('peer_address')} "
            f"(AS {session.get('remote_as') or 'unknown'}), state "
            f"{session.get('state') or 'unknown'}"
        )
        if session.get("accepted_prefixes") is not None:
            detail += f", {session['accepted_prefixes']} prefix(es) accepted"
        context.add_finding(f"BGP {hostname}", detail,
                            href=f"/devices/{device_id}", engine="routing")
    if len(sessions) > 12:
        context.add_finding(
            "More BGP sessions",
            f"{len(sessions) - 12} further session(s) not listed here",
            href="/topology?view=bgp", engine="routing",
        )
    context.cite("BGP Observations",
                 f"{len(sessions)} session(s) across {len(context.device_ids)} "
                 "device(s)", "/topology?view=bgp")
    context.add_gap(BGP_EVIDENCE_LIMIT)
    return True


# -- engine: OSPF ----------------------------------------------------------

def ospf_for_devices(context: InvestigationContext) -> bool:
    graph = context.graph
    if not context.device_ids:
        return False
    adjacencies: list[tuple[str, dict[str, Any]]] = []
    for device_id in context.device_ids:
        for item in routing_evidence_for(graph, device_id)["ospf_adjacencies"]:
            adjacencies.append((device_id, item))
    context.facts["ospf_adjacencies_total"] = len(adjacencies)
    if not adjacencies:
        context.add_gap(
            "No device in scope reported OSPF neighbours at the last "
            "discovery, so Atlas holds no OSPF evidence for it."
        )
        return True
    full = [
        item for item in adjacencies
        if str(item[1].get("state") or "").casefold().startswith("full")
    ]
    context.facts["ospf_full"] = len(full)
    for device_id, item in adjacencies[:12]:
        device = device_by_id(graph, device_id)
        hostname = getattr(device, "hostname", device_id)
        detail = (
            f"neighbour {item.get('neighbor_router_id')} on "
            f"{item.get('local_interface') or 'an interface'}, state "
            f"{item.get('state') or 'unknown'}"
        )
        area = item.get("area_id")
        detail += f", area {area}" if area else ""
        context.add_finding(f"OSPF {hostname}", detail,
                            href=f"/devices/{device_id}", engine="routing")
    context.cite("OSPF Observations",
                 f"{len(adjacencies)} adjacency(ies) in scope",
                 "/topology?view=ospf")
    if not any(item[1].get("area_id") for item in adjacencies):
        context.add_gap(
            "The OSPF neighbour output Atlas collects does not carry the "
            "area, so adjacencies are reported without one."
        )
    return True


# -- engine: interfaces and links ------------------------------------------

def interface_health(context: InvestigationContext) -> bool:
    graph = context.graph
    interfaces = getattr(graph, "interfaces", {}) or {}
    if not context.device_ids:
        return False
    total = 0
    down: list[str] = []
    for device_id in context.device_ids:
        device = device_by_id(graph, device_id)
        hostname = getattr(device, "hostname", device_id)
        for interface in interfaces.get(device_id, ()) or ():
            total += 1
            status = str(getattr(interface, "status", "") or "").casefold()
            protocol = str(
                getattr(interface, "protocol_status", "") or ""
            ).casefold()
            if "down" in status or "down" in protocol:
                down.append(f"{hostname} {getattr(interface, 'name', '')}")
    context.facts["interfaces_total"] = total
    context.facts["interfaces_down"] = len(down)
    if not total:
        context.add_gap(
            "Atlas holds no interface records for the devices in scope."
        )
        return True
    context.add_finding(
        "Interfaces",
        f"{total} interface(s) in scope; {len(down)} reported down"
        + (f" ({', '.join(down[:4])})" if down else ""),
        href="/topology", engine="graph",
    )
    context.add_gap(
        "Atlas records interface status and addressing, not error "
        "counters, utilisation or optical levels."
    )
    return True


def path_walk(context: InvestigationContext) -> bool:
    """Walk the path with Atlas's path engine (Part 4).

    Path Intelligence already validates reachability hop by hop against
    captured routing tables — far more than reading links from the
    graph. An investigation must ORCHESTRATE that engine, never
    substitute a weaker check for it.
    """

    source = context.entities.source
    destination = context.entities.destination
    if not (source and source.ok and destination and destination.ok):
        return False
    if not context.snapshot:
        context.add_gap(
            "Atlas holds no topology snapshot, so the path between the "
            "endpoints could not be walked."
        )
        return False

    def endpoint_name(entity) -> str:
        if entity.kind == "device":
            return entity.label
        device = device_by_id(context.graph, (entity.device_ids or (None,))[0])
        return str(getattr(device, "hostname", "") or "")

    start, end = endpoint_name(source), endpoint_name(destination)
    if not start or not end:
        return False
    try:
        from founderos_atlas.path_intelligence import investigate_path

        result = investigate_path(
            start, end, snapshot=context.snapshot,
            generated_at="", fresh=True, failed_hosts=(),
        )
    except Exception:  # the engine's own failure is not the answer
        context.add_gap(
            "The path walk could not run, so reachability between the "
            "endpoints is unverified."
        )
        return False

    context.facts["path_status"] = result.status
    context.facts["path_hops"] = list(getattr(result, "path", ()) or ())
    context.facts["path_start"] = start
    context.facts["path_end"] = end
    context.facts["path_failure"] = getattr(result, "failure_summary", "")
    context.facts["path_confidence"] = getattr(
        result, "confidence_band", ""
    )
    hops = " → ".join(context.facts["path_hops"])
    context.add_finding(
        "Path walk",
        f"{start} → {end}: {result.status}" + (f" via {hops}" if hops else ""),
        href="/paths?scope=all", engine="path",
    )
    context.cite("Path evidence",
                 f"{start} → {end} walked against the captured routing "
                 "tables", "/paths?scope=all")
    for unknown in tuple(getattr(result, "unknowns", ()) or ())[:3]:
        context.add_gap(str(unknown))
    return True


def wan_path(context: InvestigationContext) -> bool:
    """Links between the two endpoints' devices, from the graph."""

    graph = context.graph
    source = context.entities.source
    destination = context.entities.destination
    if not (source and source.ok and destination and destination.ok):
        return False
    near = set(source.device_ids)
    far = set(destination.device_ids)
    connecting = []
    for link in getattr(graph, "links", ()) or ():
        local = str(getattr(link, "local_enterprise_id", "") or "")
        remote = str(getattr(link, "remote_enterprise_id", "") or "")
        if (local in near and remote in far) or (local in far and remote in near):
            connecting.append(link)
    context.facts["links_between"] = len(connecting)
    if not connecting:
        context.add_gap(
            f"Atlas has discovered no direct link between {source.label} "
            f"and {destination.label}. They may still be connected "
            "through devices Atlas has not discovered."
        )
        return True
    for link in connecting[:6]:
        context.add_finding(
            "Link",
            f"{link.local_hostname} {link.local_interface or ''} → "
            f"{link.remote_hostname} {link.remote_interface or ''} "
            f"({getattr(link, 'protocol', 'discovered')})",
            href="/topology", engine="topology",
        )
    context.cite("Topology", f"{len(connecting)} link(s) between the "
                 "named endpoints", "/topology")
    return True


# -- engine: change history -------------------------------------------------

def recent_changes(context: InvestigationContext) -> bool:
    """Recorded changes, which is how an investigation gets a 'why now'."""

    report = context.facts.get("change_report")
    if report is None:
        context.add_gap(
            "Atlas holds no change report for this scope, so it cannot "
            "say whether anything changed recently."
        )
        return True
    count = int(report.get("count") or 0)
    context.add_finding(
        "Recent changes",
        f"{count} recorded change(s)" + (
            f" in the {context.request.time_range}"
            if context.request.time_range else ""
        ),
        href="/changes", engine="changes",
    )
    context.cite("Change Report", f"{count} recorded change(s)", "/changes")
    return True
