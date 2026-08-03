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


# -- engine: policy validation (PR-171) -------------------------------------
#
# The validation template ORCHESTRATES the existing policy engine — the
# PR-167 precedent, applied again: the connectivity template calls Path
# Intelligence rather than re-reading links, and this calls
# PolicyEngine.evaluate() rather than re-implementing any matching.
# Nothing below parses configuration, evaluates a rule, or computes a
# disposition; it selects the subject's rules by tag and aggregates
# what the engine concluded.

def enterprise_scope(context: InvestigationContext) -> bool:
    """Resolve the ENTERPRISE scope to every managed device.

    "Across the enterprise" is a positive scope (PR-171): when the
    operator named no narrower place, the whole estate is what gets
    judged — stated, never silently substituted. A named scope keeps
    the device list ``locate_entities`` already resolved.
    """

    if context.device_ids:
        return True                      # a narrower scope already won
    devices = tuple(getattr(context.graph, "devices", ()) or ())
    context.device_ids = tuple(
        str(getattr(device, "enterprise_id", "")) for device in devices
    )
    context.cite(
        "Enterprise Graph",
        f"{len(context.device_ids)} managed device(s) in scope",
        "/topology",
    )
    return True


def aggregate_policy_report(
    report, *, tags: tuple[str, ...], scope_hostnames: frozenset[str],
    rule_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """One subject's slice of a policy report, aggregated honestly.

    Pure and shared: the investigation engine and the Advisor's
    validate handler both read THIS, so the two paths can never
    disagree about what the policy engine concluded. Every number is a
    count of the engine's own dispositions — pass, fail, warning,
    unknown — plus ``not_applicable`` (PR-172, R1): an evaluation whose
    rule did not apply to the device. A device that does not run the
    subject at all is never counted as passing its policies.

    Per evaluation the precedence is: **unknown first** (absent
    evidence outranks everything — Atlas cannot even establish whether
    the rule applies), then **not applicable**, then the judged
    disposition. Per device: ``devices_judged`` holds only devices
    with at least one judged evaluation; ``devices_not_applicable``
    holds devices that were evaluated but where nothing applied.
    """

    tag_set = set(tags)
    evaluations = [
        item for item in getattr(report, "evaluations", ())
        if tag_set & set(getattr(item.policy, "tags", ()))
    ]
    if rule_ids:
        # PR-172 (R9): when the caller derived a capability, only its
        # vetted rules may shape the verdict — a mask-blind rule that
        # happens to share the subject's tag stays out.
        evaluations = [
            item for item in evaluations
            if str(getattr(item.policy, "policy_id", "")) in rule_ids
        ]
    if scope_hostnames:
        folded = {name.casefold() for name in scope_hostnames}
        evaluations = [
            item for item in evaluations
            if str(item.hostname or "").casefold() in folded
            or str(item.device_id or "").casefold() in folded
        ]

    by_policy: dict[str, dict[str, Any]] = {}
    devices_evaluated: set[str] = set()
    devices_judged: set[str] = set()
    devices_na_seen: set[str] = set()
    counts = {"pass": 0, "fail": 0, "warning": 0, "unknown": 0,
              "not_applicable": 0}
    unknown_reasons: dict[str, int] = {}
    for item in evaluations:
        status = item.status
        applicable = bool(getattr(item, "applicable", True))
        device = str(item.hostname or item.device_id)
        devices_evaluated.add(device)
        # Precedence: unknown (no evidence) > not applicable > judged.
        if status == "unknown":
            bucket = "unknown"
        elif not applicable:
            bucket = "not_applicable"
        else:
            bucket = status
        if bucket in counts:
            counts[bucket] += 1
        if bucket in ("pass", "fail", "warning"):
            devices_judged.add(device)
        elif bucket == "not_applicable":
            devices_na_seen.add(device)
        row = by_policy.setdefault(item.policy.policy_id, {
            "policy_id": item.policy.policy_id,
            "name": item.policy.name,
            "severity": str(getattr(item.policy, "severity", "") or ""),
            "pass": 0, "fail": 0, "warning": 0, "unknown": 0,
            "not_applicable": 0,
            "failed_devices": [],
        })
        if bucket in row:
            row[bucket] += 1
        if bucket == "fail":
            row["failed_devices"].append(device)
        if bucket == "unknown":
            # The ENGINE'S OWN reason lives in the result's conclusion
            # ("...: unknown — required evidence (running-config) is
            # not available."); ``summary`` is kept as a fallback for
            # older result shapes.
            reason = ""
            result = getattr(item, "result", None)
            if result is not None:
                reason = str(
                    getattr(result, "conclusion", "")
                    or getattr(result, "summary", "")
                    or ""
                )
            reason = reason or "the evidence this policy needs is absent"
            unknown_reasons[reason] = unknown_reasons.get(reason, 0) + 1

    return {
        "policies": sorted(by_policy.values(),
                           key=lambda row: row["policy_id"]),
        "counts": counts,
        "devices_judged": frozenset(devices_judged),
        # Devices where the subject's rules were evaluated but none
        # applied — the device does not run the subject. Reported as
        # its own state, never as compliant.
        "devices_not_applicable": frozenset(devices_na_seen - devices_judged),
        "devices_evaluated": frozenset(devices_evaluated),
        "unknown_reasons": unknown_reasons,
        "evaluated": len(evaluations),
    }


def policy_validation(context: InvestigationContext) -> bool:
    """Judge the subject's configuration with the EXISTING policy
    engine, and report its dispositions without editing them.

    Honesty rules, in order of importance:

    * **No matching policies is a refusal, never a pass.** A subject
      whose tags select zero rules cannot be judged, and saying
      "compliant" about it would be the exact confident-answer-without-
      evidence failure this PR exists to prevent (risk R3).
    * A device the engine could not judge stays UNKNOWN, with the
      engine's own reason attached.
    * Devices in scope that produced no evaluation at all are counted
      and named — "not judged" is part of the answer, not a footnote.
    """

    from .subjects import label_for, subject as subject_of

    request = context.request
    descriptor = subject_of(request.subject or request.protocol)
    label = label_for(request.subject or request.protocol)
    runner = context.facts.get("policy_runner")
    if not callable(runner):
        context.add_gap(
            "Policy evaluation is not available in this context, so the "
            f"{label} configuration could not be judged."
        )
        return False

    tags = tuple(descriptor.policy_tags) if descriptor else ()
    if not tags:
        context.facts["validation_no_policies"] = True
        context.add_gap(
            f"Atlas has no configuration policies for {label}, so it "
            "cannot judge this configuration — and it will not claim "
            "compliance it has not checked."
        )
        return False

    report = runner()
    if report is None:
        context.add_gap(
            "The policy engine returned no report, so the "
            f"{label} configuration could not be judged."
        )
        return False

    # PR-172 (R9 + governance): the capability's vetted rule list —
    # only rules the masked view can actually see may shape a verdict,
    # and they are derived from the pack THIS REPORT was judged with
    # (the governance-effective pack when the caller supplied it), so
    # the verdict and the policy page read the same rule set. Reports
    # that do not declare their pack (test stubs) keep tag selection.
    from .validation import capability as capability_of

    report_pack = getattr(report, "pack", None)
    cap = (
        capability_of(request.subject or request.protocol, report_pack)
        if report_pack is not None else None
    )
    vetted_rules = frozenset(cap.rules) if cap else frozenset()

    # Hostnames for the devices in scope, so a site-scoped validation
    # judges only that site. Enterprise scope filters nothing.
    scope_hostnames: frozenset[str] = frozenset()
    if request.scope not in ("", "enterprise"):
        names = set()
        for device_id in context.device_ids:
            device = device_by_id(context.graph, device_id)
            if device is not None:
                names.add(str(getattr(device, "hostname", "") or device_id))
            else:
                names.add(str(device_id))
        scope_hostnames = frozenset(names)

    aggregate = aggregate_policy_report(
        report, tags=tags, scope_hostnames=scope_hostnames,
        rule_ids=vetted_rules,
    )
    context.facts["validation"] = {
        "subject": label,
        "counts": aggregate["counts"],
        "evaluated": aggregate["evaluated"],
        "policies": len(aggregate["policies"]),
    }

    from .validation import verdict_for

    if not aggregate["policies"]:
        if report_pack is not None and cap is not None:
            # The pack DOES carry rules for this subject — the scope
            # simply produced no evaluations (no evidence for these
            # devices). Saying "no policies" here would name the wrong
            # cause; the projection says "not enough evidence".
            context.facts["validation_verdict"] = verdict_for(
                aggregate, scope_count=len(context.device_ids),
            )
            context.add_gap(
                f"The policy engine produced no {label} evaluations "
                "for the devices in this scope, so this configuration "
                "could not be judged."
            )
            return False
        # Tags are declared but the pack this report was judged with
        # carries none of them (or a stub report declares no pack) —
        # the same refusal, reached one step later.
        context.facts["validation_no_policies"] = True
        context.add_gap(
            f"Atlas has no configuration policies for {label} in the "
            "active policy pack, so it cannot judge this configuration."
        )
        return False

    # PR-172: the verdict projection — computed HERE, where the
    # aggregate lives, so the summary layer only ever repeats it.
    context.facts["validation_verdict"] = verdict_for(
        aggregate, scope_count=len(context.device_ids),
    )

    for row in aggregate["policies"]:
        judged = row["pass"] + row["fail"] + row["warning"]
        not_applicable = int(row.get("not_applicable") or 0)
        na_note = (
            f" Not applicable on {not_applicable} device(s)."
            if not_applicable else ""
        )
        if row["fail"]:
            failed = ", ".join(sorted(row["failed_devices"])[:6])
            more = len(row["failed_devices"]) - 6
            context.add_finding(
                f"{row['name']} — {row['fail']} device(s) fail",
                f"{row['policy_id']}: {row['pass']} pass, {row['fail']} "
                f"fail of {judged} judged. Failing: {failed}"
                + (f" and {more} more" if more > 0 else "") + "."
                + na_note,
                href="/policy", engine="policy",
            )
        elif judged:
            context.add_finding(
                f"{row['name']} — {row['pass']} of {judged} judged "
                "device(s) pass",
                f"{row['policy_id']}: no failures among the devices the "
                "policy engine could judge." + na_note,
                href="/policy", engine="policy",
            )
        elif not_applicable:
            # PR-172 (R1): every evaluation was not applicable — the
            # subject is not configured on any device this rule saw.
            # Stated as its own outcome, never as a pass.
            context.add_finding(
                f"{row['name']} — not applicable on "
                f"{not_applicable} device(s)",
                f"{row['policy_id']}: no device this rule evaluated has "
                "the configuration it judges, so there is nothing to "
                "certify — and Atlas does not report absence as "
                "compliance.",
                href="/policy", engine="policy",
            )

    for reason, count in sorted(aggregate["unknown_reasons"].items()):
        context.add_gap(
            f"{count} evaluation(s) are unknown: {reason}"
        )

    # Devices where the subject's rules were evaluated but none applied
    # — the device does not run the subject (PR-172, R1). A positive
    # determination, stated as its own state: never compliant, never a
    # gap (nothing is missing — Atlas looked and the subject is not
    # there).
    not_applicable_devices = aggregate["devices_not_applicable"]
    if not_applicable_devices:
        context.facts["validation_not_applicable"] = (
            len(not_applicable_devices)
        )

    # Devices in scope the engine never evaluated at all — usually no
    # collected running-config. Counted, and the reason stated.
    scope_count = len(context.device_ids)
    evaluated_devices = aggregate["devices_evaluated"]
    if scope_count and len(evaluated_devices) < scope_count:
        missing = scope_count - len(evaluated_devices)
        context.facts["validation_not_judged"] = missing
        context.add_gap(
            f"{missing} of {scope_count} device(s) in scope were not "
            "judged — Atlas holds no configuration evidence for them, so "
            f"their {label} configuration is unknown, not compliant."
        )

    context.cite(
        "Policy Engine Results",
        f"{aggregate['evaluated']} evaluation(s) across "
        f"{len(aggregate['policies'])} {label} polic"
        + ("y" if len(aggregate["policies"]) == 1 else "ies"),
        "/policy",
    )
    return True
