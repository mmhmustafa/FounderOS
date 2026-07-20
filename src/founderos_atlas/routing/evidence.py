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
# Device output often parenthesizes the VRF — "(VRF default)" — and a
# greedy character class swallowed the closing paren, minting a phantom
# "default)" VRF whose BGP domains rendered as DUPLICATE boxes beside
# the real ones. Trailing punctuation is not identity.
_VRF = re.compile(r"(?i)\bVRF\s+([^,\s)]+)")
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


_STATE_WORDS = {
    "established": "established",
    "estab": "established",
    "active": "active",
    "idle": "idle",
    "connect": "connect",
    "opensent": "opensent",
    "openconfirm": "openconfirm",
}


def _state_column(text: str) -> int | None:
    """Where this device said its state column is.

    Summary layouts differ per platform and per version — FRR appends
    PfxSnt and Desc after the state, EOS drops TblVer, IOS ends at the
    state. Counting from the right (or from a fixed index) therefore
    reads a different column on each of them: on FRR it picked up the
    neighbor DESCRIPTION, so every session's state was recorded as its
    own description and no session was ever "established".

    The device prints a header naming its columns. Reading the position
    from that header is the one approach that follows a layout change
    instead of being broken by it. Columns after the state may be
    absent on a given row (an empty Desc), so the index is taken from
    the LEFT, where every layout agrees.
    """

    for line in text.splitlines():
        tokens = line.split()
        if not tokens or "Neighbor" not in tokens[0]:
            continue
        for index, token in enumerate(tokens):
            folded = token.casefold()
            if folded.startswith("state") or folded.endswith("pfxrcd"):
                return index
    return None


def _prefix_column(text: str) -> int | None:
    """A prefix count of its own, where the platform keeps one.

    IOS and FRR share one "State/PfxRcd" cell; EOS prints "State" and
    "PfxRcd" separately, so the count lives in its own column and is
    lost unless it is read there.
    """

    for line in text.splitlines():
        tokens = line.split()
        if not tokens or "Neighbor" not in tokens[0]:
            continue
        for index, token in enumerate(tokens):
            if token.casefold() == "pfxrcd":
                return index
    return None


def bgp_sessions_from_summary(
    text: str, *, source_command: str
) -> tuple[BgpSessionObservation, ...]:
    """Parse common IOS/EOS/NX-OS/FRR and Junos summary rows."""

    if not text.strip() or text.lstrip().startswith("%"):
        return ()
    state_at = _state_column(text)
    prefixes_at = _prefix_column(text)
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
        # The header names the column; without one, fall back to the
        # last token, which is right on the layouts that end at state.
        cell = ""
        if state_at is not None and len(parts) > state_at:
            cell = parts[state_at].rstrip(",")
        if not cell:
            cell = parts[-1].rstrip(",")
        folded_cell = cell.casefold()
        prefixes: int | None = None
        if cell.isdigit():
            # A prefix count in the state column IS the established
            # state — that is what the shared "State/PfxRcd" means.
            state = "established"
            prefixes = int(cell)
        elif folded_cell in _STATE_WORDS:
            state = _STATE_WORDS[folded_cell]
        else:
            matched = next(
                (
                    value for key, value in _STATE_WORDS.items()
                    if key in folded_cell
                ),
                None,
            )
            if matched is not None:
                state = matched
            else:
                # Never silently label an unreadable cell "established";
                # an unknown state is reported as what was seen.
                state = folded_cell or "unknown"
        if (
            prefixes is None
            and prefixes_at is not None
            and len(parts) > prefixes_at
            and parts[prefixes_at].isdigit()
        ):
            prefixes = int(parts[prefixes_at])
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
