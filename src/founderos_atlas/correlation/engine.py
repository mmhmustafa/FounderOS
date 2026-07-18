"""The Atlas Evidence Correlation Engine (PR-043.7, FUSION).

Consumes NORMALIZED canonical observations — never raw parser output —
and fuses every independent evidence source into enterprise
relationships with deterministic priority, honest confidence, and full
provenance:

    1. Verified interface ownership   (peer address owned by an interface)
    2. Matching point-to-point subnets (/30, /31)
    3. LLDP / CDP link-layer announcements
    4. OSPF neighbor adjacencies
    5. BGP peer sessions
    6. Static routes
    7. ARP / MAC correlation
    8. Configuration references (interface descriptions, config text)
    9. Hostname matching

Lower-priority observations strengthen confidence; they never override
stronger evidence. Conflicting observations are reported, not guessed.
The engine is vendor-independent and source-extensible: any future
evidence source (SNMP, telemetry, NetFlow, cloud APIs, …) contributes
normalized observations through the same inputs without changing this
architecture. Re-running correlation over a grown evidence set resolves
previously provisional peers without rediscovery (Part 7).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from ipaddress import ip_address, ip_interface
import re
from typing import Any

from .models import (
    AddressClaim,
    AddressOwnershipIndex,
    CONFIDENCE_BASE,
    CONFIDENCE_CAP,
    CORROBORATION_BONUS,
    CorrelatedRelationship,
    CorrelationResult,
    EVIDENCE_KINDS,
    KIND_INTERFACE,
    KIND_LOOPBACK,
    KIND_MANAGEMENT,
    KIND_ROUTER_ID,
    KIND_SECONDARY,
    KIND_VIRTUAL,
    PRIORITY_BGP,
    PRIORITY_CONFIG_REFERENCE,
    PRIORITY_HOSTNAME,
    PRIORITY_INTERFACE_OWNERSHIP,
    PRIORITY_LINK_LAYER,
    PRIORITY_OSPF,
    PRIORITY_P2P_SUBNET,
    PRIORITY_STATIC_ROUTE,
    REL_BGP,
    REL_INFERRED,
    REL_LAYER2,
    REL_LAYER3,
    REL_OSPF,
    REL_STATIC,
    REL_UNKNOWN,
    REL_VERIFIED_PHYSICAL,
    REL_VERIFIED_ROUTED,
    RelationshipEvidence,
    UnresolvedObservation,
)

# Point-to-point prefixes: exactly two usable endpoints.
_P2P_PREFIXES = frozenset({30, 31})

_PROTOCOL_PRIORITY = {
    "cdp": PRIORITY_LINK_LAYER,
    "lldp": PRIORITY_LINK_LAYER,
    "manual": PRIORITY_LINK_LAYER,
    "ospf": PRIORITY_OSPF,
    "isis": PRIORITY_OSPF,
    "bgp": PRIORITY_BGP,
    "static": PRIORITY_STATIC_ROUTE,
    "inferred": PRIORITY_HOSTNAME,
}

_LOOPBACK_NAME = re.compile(r"^(lo|loopback)", re.IGNORECASE)
_HOSTNAME_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _valid_ip(value: Any) -> str | None:
    try:
        return str(ip_address(str(value).strip()))
    except (ValueError, TypeError):
        return None


def _claimable_ip(value: Any) -> str | None:
    """An address a device can meaningfully OWN as identity evidence.

    Host-local and non-unicast addresses (127.0.0.1 on every Linux
    device's ``lo``, 0.0.0.0, multicast) can never identify a remote
    peer; claiming them would manufacture ownership "conflicts" between
    unrelated devices and degrade health over nothing.
    """

    cleaned = _valid_ip(value)
    if cleaned is None:
        return None
    parsed = ip_address(cleaned)
    if parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast:
        return None
    return cleaned


class EvidenceCorrelationEngine:
    """Deterministic evidence fusion over canonical devices and observations.

    Inputs are snapshot-shaped mappings (the canonical normalization
    output): devices with their interfaces and metadata, plus neighbor
    observations. Output is a ``CorrelationResult`` — fused
    relationships, unresolved observations, and the enterprise address
    ownership index.
    """

    def correlate(
        self,
        devices: Iterable[Mapping[str, Any]],
        edges: Iterable[Mapping[str, Any]],
        *,
        observed_at: str | None = None,
    ) -> CorrelationResult:
        device_list = [dict(item) for item in devices]
        edge_list = [dict(item) for item in edges]
        ownership = build_ownership_index(device_list)
        hostname_map = _hostname_map(device_list)
        family_by_id = {
            str(d["device_id"]): _platform_family(d) for d in device_list
        }

        # pair (sorted device_id 2-tuple) -> list of evidence
        evidence: dict[tuple[str, str], list[RelationshipEvidence]] = {}
        unresolved: list[UnresolvedObservation] = []
        warnings = [
            f"address {conflict.address} is claimed by multiple devices — "
            "excluded from resolution until the conflict is explained"
            for conflict in ownership.conflicts
        ]

        def add(pair: tuple[str, str], item: RelationshipEvidence) -> None:
            evidence.setdefault(pair, []).append(item)

        # -- 1. resolve neighbor observations through ownership + hostnames --
        for edge in edge_list:
            local_id = str(edge["local_device_id"])
            protocol = str(edge.get("protocol") or "manual").casefold()
            metadata = dict(edge.get("metadata") or {})
            local_interface = str(edge.get("local_interface") or "")
            remote_identity = str(edge.get("remote_hostname") or "")
            resolved_id, how, address = _resolve_remote(
                edge, metadata, ownership, hostname_map
            )
            if resolved_id is None:
                unresolved.append(
                    UnresolvedObservation(
                        local_device_id=local_id,
                        local_interface=local_interface,
                        remote_identity=remote_identity,
                        protocol=protocol,
                        reason=(
                            "no discovered device owns this identity — "
                            "insufficient evidence, kept as observed"
                        ),
                    )
                )
                continue
            if resolved_id == local_id:
                continue  # self-reference (an own address echoed back)
            pair = tuple(sorted((local_id, resolved_id)))
            priority = _PROTOCOL_PRIORITY.get(protocol, PRIORITY_HOSTNAME)
            source = metadata.get("source_command")
            add(pair, RelationshipEvidence(
                priority=priority,
                kind=EVIDENCE_KINDS[priority],
                detail=(
                    f"{protocol.upper()} observation on {local_id} "
                    f"({local_interface}) names {remote_identity}"
                ),
                observed_by=local_id,
                source_command=str(source) if source else None,
                platform_family=family_by_id.get(local_id),
                local_interface=local_interface,
                remote_interface=(
                    str(edge["remote_interface"])
                    if edge.get("remote_interface") else None
                ),
            ))
            if how == "ownership" and address is not None:
                claim = ownership.owner_of(address)
                add(pair, RelationshipEvidence(
                    priority=PRIORITY_INTERFACE_OWNERSHIP,
                    kind=EVIDENCE_KINDS[PRIORITY_INTERFACE_OWNERSHIP],
                    detail=(
                        f"address {address} named by the observation is "
                        f"owned by {resolved_id}"
                        + (
                            f" ({claim.kind} {claim.interface})"
                            if claim and claim.interface
                            else f" ({claim.kind})" if claim else ""
                        )
                    ),
                    observed_by=local_id,
                    source_command=str(source) if source else None,
                    platform_family=family_by_id.get(local_id),
                    local_interface=local_interface,
                    remote_interface=claim.interface if claim else None,
                ))
            elif how == "hostname":
                add(pair, RelationshipEvidence(
                    priority=PRIORITY_HOSTNAME,
                    kind=EVIDENCE_KINDS[PRIORITY_HOSTNAME],
                    detail=(
                        f"observed name {remote_identity!r} matches the "
                        f"canonical hostname of {resolved_id}"
                    ),
                    observed_by=local_id,
                    source_command=str(source) if source else None,
                    platform_family=family_by_id.get(local_id),
                    local_interface=local_interface,
                ))

        # -- 2. matching point-to-point subnets --------------------------------
        for pair, items in _p2p_subnet_evidence(device_list, family_by_id):
            for item in items:
                add(pair, item)

        # -- 3. configuration references (interface descriptions) --------------
        for pair, item in _description_evidence(
            device_list, hostname_map, family_by_id
        ):
            add(pair, item)

        # -- fuse ---------------------------------------------------------------
        relationships = []
        for pair in sorted(evidence):
            items = tuple(sorted(set(evidence[pair])))
            relationships.append(
                _fuse(pair, items, observed_at=observed_at)
            )
        return CorrelationResult(
            relationships=tuple(relationships),
            unresolved=tuple(
                sorted(
                    unresolved,
                    key=lambda item: (
                        item.local_device_id, item.local_interface,
                        item.remote_identity, item.protocol,
                    ),
                )
            ),
            ownership=ownership,
            warnings=tuple(warnings),
        )


def build_ownership_index(
    devices: Iterable[Mapping[str, Any]],
) -> AddressOwnershipIndex:
    """The Enterprise Address Ownership Index (Part 4).

    Claims every management IP, loopback IP, interface IP, secondary IP,
    router ID, and virtual IP for its canonical device. Conflicting
    claims (two devices, one address) are recorded and excluded — never
    guessed.
    """

    claims: list[AddressClaim] = []
    for device in devices:
        device_id = str(device["device_id"])
        management = _claimable_ip(device.get("management_ip"))
        if management:
            claims.append(AddressClaim(
                address=management, device_id=device_id, kind=KIND_MANAGEMENT,
                detail="management address",
            ))
        for interface in device.get("interfaces") or ():
            name = str(interface.get("name") or "")
            metadata = dict(interface.get("metadata") or {})
            source = metadata.get("source_command")
            address = _claimable_ip(interface.get("ip_address"))
            if address:
                kind = (
                    KIND_LOOPBACK if _LOOPBACK_NAME.match(name)
                    else KIND_INTERFACE
                )
                claims.append(AddressClaim(
                    address=address, device_id=device_id, kind=kind,
                    interface=name,
                    source_command=str(source) if source else None,
                    detail=f"assigned to {name}",
                ))
            for secondary in metadata.get("secondary_ips") or ():
                cleaned = _claimable_ip(str(secondary).split("/", 1)[0])
                if cleaned:
                    claims.append(AddressClaim(
                        address=cleaned, device_id=device_id,
                        kind=KIND_SECONDARY, interface=name,
                        source_command=str(source) if source else None,
                        detail=f"secondary on {name}",
                    ))
        metadata = dict(device.get("metadata") or {})
        # A canonical (federated) device can carry several management
        # addresses — one per merged observation. Every one of them is
        # this device's claim; only the first rides in ``management_ip``.
        for extra in metadata.get("management_ips") or ():
            cleaned = _claimable_ip(extra)
            if cleaned and cleaned != management:
                claims.append(AddressClaim(
                    address=cleaned, device_id=device_id,
                    kind=KIND_MANAGEMENT, detail="management address",
                ))
        for key in ("router_id", "bgp_router_id", "ospf_router_id"):
            router_id = _claimable_ip(metadata.get(key))
            if router_id:
                claims.append(AddressClaim(
                    address=router_id, device_id=device_id,
                    kind=KIND_ROUTER_ID,
                    detail=key.replace("_", " "),
                ))
        for virtual in metadata.get("virtual_ips") or ():
            cleaned = _claimable_ip(virtual)
            if cleaned:
                claims.append(AddressClaim(
                    address=cleaned, device_id=device_id, kind=KIND_VIRTUAL,
                    detail="virtual address",
                ))
    return AddressOwnershipIndex(tuple(claims))


# -- internals ----------------------------------------------------------------------


def _platform_family(device: Mapping[str, Any]) -> str | None:
    device_id = str(device.get("device_id") or "")
    if ":" in device_id:
        return device_id.split(":", 1)[0]
    return None


def _hostname_map(devices: list[dict[str, Any]]) -> dict[str, str]:
    """observed name (casefolded) -> device_id, including aliases."""

    table: dict[str, str] = {}
    for device in devices:
        device_id = str(device["device_id"])
        table.setdefault(str(device.get("hostname") or "").casefold(), device_id)
        identity = dict(device.get("metadata") or {}).get("identity") or {}
        for alias in identity.get("aliases") or ():
            table.setdefault(str(alias).casefold(), device_id)
    table.pop("", None)
    return table


def _resolve_remote(
    edge: Mapping[str, Any],
    metadata: Mapping[str, Any],
    ownership: AddressOwnershipIndex,
    hostname_map: Mapping[str, str],
) -> tuple[str | None, str | None, str | None]:
    """(device_id, how, address) for one observation's remote identity.

    Address evidence is consulted strongest-first: the adjacency /
    peer / management address through the ownership index, then the
    observed name as an address, then the observed name as a hostname.
    """

    for key in ("adjacency_address", "peer_address"):
        address = _valid_ip(metadata.get(key))
        if address is not None:
            claim = ownership.owner_of(address)
            if claim is not None:
                return claim.device_id, "ownership", address
    address = _valid_ip(edge.get("remote_management_ip"))
    if address is not None:
        claim = ownership.owner_of(address)
        if claim is not None:
            return claim.device_id, "ownership", address
    named = str(edge.get("remote_hostname") or "").strip()
    named_address = _valid_ip(named)
    if named_address is not None:
        claim = ownership.owner_of(named_address)
        if claim is not None:
            return claim.device_id, "ownership", named_address
        return None, None, None  # an address no one provably owns
    resolved = hostname_map.get(named.casefold())
    if resolved is not None:
        return resolved, "hostname", None
    return None, None, None


def _p2p_subnet_evidence(
    devices: list[dict[str, Any]],
    family_by_id: Mapping[str, str | None],
) -> list[tuple[tuple[str, str], list[RelationshipEvidence]]]:
    """Priority-2 evidence: exactly two devices sharing a /30 or /31."""

    members: dict[str, list[tuple[str, str, str]]] = {}
    for device in devices:
        device_id = str(device["device_id"])
        for interface in device.get("interfaces") or ():
            address = _valid_ip(interface.get("ip_address"))
            metadata = dict(interface.get("metadata") or {})
            prefix = metadata.get("prefix_length")
            if address is None or prefix not in _P2P_PREFIXES:
                continue
            network = str(ip_interface(f"{address}/{prefix}").network)
            members.setdefault(network, []).append(
                (device_id, str(interface.get("name") or ""), address)
            )
    produced: list[tuple[tuple[str, str], list[RelationshipEvidence]]] = []
    for network in sorted(members):
        entries = sorted(members[network])
        distinct = sorted({entry[0] for entry in entries})
        if len(distinct) != 2:
            continue  # zero/one device proves nothing; 3+ is not point-to-point
        pair = (distinct[0], distinct[1])
        items = []
        for device_id, interface, address in entries:
            other = pair[1] if device_id == pair[0] else pair[0]
            other_entry = next(e for e in entries if e[0] == other)
            items.append(RelationshipEvidence(
                priority=PRIORITY_P2P_SUBNET,
                kind=EVIDENCE_KINDS[PRIORITY_P2P_SUBNET],
                detail=(
                    f"{device_id} {interface} ({address}) and {other} "
                    f"{other_entry[1]} ({other_entry[2]}) share "
                    f"point-to-point subnet {network}"
                ),
                observed_by=device_id,
                source_command="show interface",
                platform_family=family_by_id.get(device_id),
                local_interface=interface,
                remote_interface=other_entry[1],
            ))
        produced.append((pair, items))
    return produced


def _description_evidence(
    devices: list[dict[str, Any]],
    hostname_map: Mapping[str, str],
    family_by_id: Mapping[str, str | None],
) -> list[tuple[tuple[str, str], RelationshipEvidence]]:
    """Priority-8 evidence: an interface description naming another
    canonical device (e.g. ``LINK-TO-edge1-ISP-EDGE``)."""

    produced = []
    for device in devices:
        device_id = str(device["device_id"])
        for interface in device.get("interfaces") or ():
            description = str(interface.get("description") or "")
            if not description:
                continue
            tokens = {
                token.casefold()
                for token in _HOSTNAME_TOKEN.findall(description)
            }
            # Also try hyphen-joined sub-tokens ("LINK-TO-edge1-ISP-EDGE"
            # contains "edge1" only after splitting on hyphens).
            for token in tuple(tokens):
                tokens.update(part for part in token.split("-") if part)
            referenced = sorted({
                hostname_map[token] for token in tokens
                if token in hostname_map and hostname_map[token] != device_id
            })
            metadata = dict(interface.get("metadata") or {})
            source = metadata.get("source_command")
            for other in referenced:
                pair = tuple(sorted((device_id, other)))
                produced.append((pair, RelationshipEvidence(
                    priority=PRIORITY_CONFIG_REFERENCE,
                    kind=EVIDENCE_KINDS[PRIORITY_CONFIG_REFERENCE],
                    detail=(
                        f"{device_id} interface "
                        f"{interface.get('name')} description "
                        f"{description!r} references {other}"
                    ),
                    observed_by=device_id,
                    source_command=str(source) if source else None,
                    platform_family=family_by_id.get(device_id),
                    local_interface=str(interface.get("name") or ""),
                )))
    return produced


def _fuse(
    pair: tuple[str, str],
    items: tuple[RelationshipEvidence, ...],
    *,
    observed_at: str | None,
) -> CorrelatedRelationship:
    """One relationship from every observation of one device pair.

    Type comes from the evidence-kind combination; confidence is the
    strongest priority's base plus a bonus per additional independent
    evidence kind, capped. Interface attribution follows the strongest
    evidence that names interfaces; disagreement between evidence
    sources over interfaces is recorded as a conflict, never guessed
    away.
    """

    kinds = {item.kind for item in items}
    relationship_type = _decide_type(kinds)
    strongest = min(item.priority for item in items)
    confidence = min(
        CONFIDENCE_CAP,
        CONFIDENCE_BASE[strongest] + CORROBORATION_BONUS * (len(kinds) - 1),
    )
    left, right = pair
    left_interface, right_interface, conflicts = _attribute_interfaces(
        pair, items
    )
    return CorrelatedRelationship(
        left_device_id=left,
        right_device_id=right,
        relationship_type=relationship_type,
        confidence=confidence,
        evidence=items,
        left_interface=left_interface,
        right_interface=right_interface,
        observed_at=observed_at,
        conflicts=conflicts,
    )


def _decide_type(kinds: set[str]) -> str:
    if "link-layer" in kinds:
        return REL_VERIFIED_PHYSICAL
    if "p2p-subnet" in kinds and (
        kinds & {"ospf-neighbor", "bgp-peer", "interface-ownership"}
    ):
        return REL_VERIFIED_ROUTED
    if "p2p-subnet" in kinds:
        return REL_LAYER3
    if "ospf-neighbor" in kinds:
        return REL_OSPF
    if "bgp-peer" in kinds:
        return REL_BGP
    if "static-route" in kinds:
        return REL_STATIC
    if "arp-mac" in kinds:
        return REL_LAYER2
    if kinds & {"config-reference", "hostname-match", "interface-ownership"}:
        return REL_INFERRED
    return REL_UNKNOWN


def _attribute_interfaces(
    pair: tuple[str, str],
    items: tuple[RelationshipEvidence, ...],
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Pick the (left, right) interface names from the strongest
    interface-bearing evidence; report disagreements as conflicts."""

    left, right = pair
    per_side: dict[str, dict[str, int]] = {left: {}, right: {}}
    for item in sorted(items):
        observer = item.observed_by
        other = right if observer == left else left
        if observer in per_side and item.local_interface:
            # A session pseudo-interface ("bgp") is not a port.
            if item.local_interface.casefold() not in ("bgp", "unknown"):
                candidates = per_side[observer]
                candidates.setdefault(item.local_interface, item.priority)
        if other in per_side and item.remote_interface:
            per_side[other].setdefault(item.remote_interface, item.priority)

    conflicts: list[str] = []
    chosen: dict[str, str | None] = {}
    for side in pair:
        candidates = per_side[side]
        if not candidates:
            chosen[side] = None
            continue
        ordered = sorted(candidates.items(), key=lambda kv: (kv[1], kv[0]))
        chosen[side] = ordered[0][0]
        distinct = sorted(set(candidates))
        if len(distinct) > 1:
            conflicts.append(
                f"evidence disagrees on the {side} interface: "
                + ", ".join(distinct)
                + f" — strongest evidence names {ordered[0][0]!r}"
            )
    return chosen[left], chosen[right], tuple(conflicts)
