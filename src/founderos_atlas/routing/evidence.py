"""Normalized, provenance-bearing OSPF and BGP observations.

These records distinguish operational evidence from configured intent.  A
configured neighbor or area may inform a view, but only an observed session
or adjacency may be labelled established/full.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
import re
from typing import Any


_LOCAL_AS = re.compile(
    r"(?i)(?:local\s+AS(?:\s+number)?|local-as)\s*[:=]?\s*(\d+)"
)
_ROUTER_ID = re.compile(
    r"(?i)(?:BGP\s+)?router\s+identifier\s*[:=]?\s*(\d+\.\d+\.\d+\.\d+)"
)
_VRF = re.compile(r"(?i)\bVRF\s+([^,\s]+)")
_AF = re.compile(r"(?i)address\s+family\s+([^\r\n,]+)")


@dataclass(frozen=True)
class OspfAdjacencyObservation:
    neighbor_router_id: str
    adjacency_address: str | None
    local_interface: str
    state: str
    process_id: str | None = None
    area_id: str | None = None
    vrf: str = "default"
    address_family: str = "ipv4"
    source_command: str = ""
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "neighbor_router_id": self.neighbor_router_id,
            "adjacency_address": self.adjacency_address,
            "local_interface": self.local_interface,
            "state": self.state,
            "process_id": self.process_id,
            "area_id": self.area_id,
            "vrf": self.vrf,
            "address_family": self.address_family,
            "source_command": self.source_command,
            "observed_at": self.observed_at,
            "evidence_state": "observed",
        }


@dataclass(frozen=True)
class BgpSessionObservation:
    peer_address: str
    remote_as: str | None
    local_as: str | None
    state: str
    vrf: str = "default"
    address_family: str = "ipv4-unicast"
    router_id: str | None = None
    accepted_prefixes: int | None = None
    source_command: str = ""
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_address": self.peer_address,
            "remote_as": self.remote_as,
            "local_as": self.local_as,
            "state": self.state,
            "vrf": self.vrf,
            "address_family": self.address_family,
            "router_id": self.router_id,
            "accepted_prefixes": self.accepted_prefixes,
            "source_command": self.source_command,
            "observed_at": self.observed_at,
            "evidence_state": "observed",
        }


def _is_ip(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def bgp_sessions_from_summary(
    text: str, *, source_command: str
) -> tuple[BgpSessionObservation, ...]:
    """Parse common IOS/EOS/NX-OS/FRR and Junos summary rows."""

    if not text.strip() or text.lstrip().startswith("%"):
        return ()
    local_match = _LOCAL_AS.search(text)
    router_match = _ROUTER_ID.search(text)
    vrf_match = _VRF.search(text)
    af_match = _AF.search(text)
    local_as = local_match.group(1) if local_match else None
    router_id = router_match.group(1) if router_match else None
    vrf = vrf_match.group(1) if vrf_match else "default"
    address_family = (
        af_match.group(1).strip().casefold().replace(" ", "-")
        if af_match else "ipv4-unicast"
    )
    sessions: list[BgpSessionObservation] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not _is_ip(parts[0]):
            continue
        peer = parts[0]
        if len(parts) >= 3 and parts[1] in {"4", "6"} and parts[2].isdigit():
            remote_as = parts[2]
        elif parts[1].isdigit():
            remote_as = parts[1]
        else:
            remote_as = None
        folded = line.casefold()
        last = parts[-1].rstrip(",")
        prefixes: int | None = None
        if last.isdigit():
            state = "established"
            prefixes = int(last)
        elif "estab" in folded:
            state = "established"
        elif "active" in folded:
            state = "active"
        elif "idle" in folded:
            state = "idle"
        elif "connect" in folded:
            state = "connect"
        else:
            state = last.casefold()
        sessions.append(
            BgpSessionObservation(
                peer_address=peer,
                remote_as=remote_as,
                local_as=local_as,
                state=state,
                vrf=vrf,
                address_family=address_family,
                router_id=router_id,
                accepted_prefixes=prefixes,
                source_command=source_command,
            )
        )
    return tuple(sessions)


def routing_metadata(
    *,
    ospf: tuple[OspfAdjacencyObservation, ...] = (),
    bgp: tuple[BgpSessionObservation, ...] = (),
) -> dict[str, Any]:
    """Canonical metadata shape shared by every platform and federation."""

    return {
        "schema_version": "1.0.0",
        "ospf_adjacencies": [item.to_dict() for item in ospf],
        "bgp_sessions": [item.to_dict() for item in bgp],
    }
