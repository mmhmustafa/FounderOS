"""Plane-aware impact model (PR-036C): management, control, data, observability.

A network change does not live on one plane. Shutting an SVI can leave
every physical link up while severing the management plane — the address
Atlas itself uses to discover and collect the device. This module
evaluates each plane deterministically from discovered evidence:

- **Management**: does the target interface own the device's active
  management address (the address Atlas connected through), a profile
  seed, or another known management address? Is a *verified* alternate
  management path available (verified = the candidate address is itself a
  proven connection address — a seed or the active management IP); a
  merely-existing second address is a candidate, never assumed reachable.
- **Control**: routing/gateway-protocol impact is predicted only from
  explicit role evidence; with none collected, Atlas reports no known
  impact and lists the missing evidence instead of inventing adjacencies.
- **Data**: gateway impact only with gateway role evidence; otherwise
  honestly unknown — while noting when discovered physical links remain
  up (Layer-2 switching continues).
- **Observability**: follows the management plane — a lost management
  address means discovery, configuration collection, and monitoring using
  that address go blind.

Every plane impact carries status, severity, its own confidence, affected
objects, supporting evidence, missing evidence, and an explanation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from founderos_atlas.root_cause.confidence import band as confidence_band

from .interfaces import LOGICAL_TYPES, TYPE_PHYSICAL, classify_interface


PLANE_MANAGEMENT = "management"
PLANE_CONTROL = "control"
PLANE_DATA = "data"
PLANE_OBSERVABILITY = "observability"

STATUS_NO_KNOWN_IMPACT = "no_known_impact"
STATUS_DEGRADED = "degraded"
STATUS_LOST = "lost"
STATUS_UNKNOWN = "unknown"

ALTERNATE_VERIFIED = "verified"
ALTERNATE_CANDIDATE = "candidate-unverified"
ALTERNATE_NONE_KNOWN = "none-known"


@dataclass(frozen=True)
class PlaneImpact:
    plane: str
    status: str
    severity: str                    # high | medium | low | none
    confidence: float                # 0.05..0.95
    explanation: str
    affected: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()

    @property
    def confidence_band(self) -> str:
        return confidence_band(self.confidence)

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plane": self.plane,
            "status": self.status,
            "severity": self.severity,
            "confidence": round(self.confidence, 4),
            "confidence_percent": self.confidence_percent,
            "confidence_band": self.confidence_band,
            "explanation": self.explanation,
            "affected": list(self.affected),
            "evidence": list(self.evidence),
            "missing_evidence": list(self.missing_evidence),
        }


@dataclass(frozen=True)
class ManagementAssessment:
    """The management-reachability conclusion feeding risk and advice."""

    owns_management_address: bool
    management_address: str | None
    alternate_status: str            # verified | candidate-unverified | none-known
    alternate_detail: str


def evaluate_planes(
    *,
    device_entry: Mapping[str, Any] | None,
    target_interface: str,
    seed_addresses: tuple[str, ...] = (),
    role_evidence: Mapping[str, Any] | None = None,
    isolated_devices: tuple[str, ...] = (),
    fresh: bool = True,
) -> tuple[tuple[PlaneImpact, ...], ManagementAssessment]:
    """Evaluate all four planes for shutting one interface.

    ``role_evidence`` is the extension point for future collectors
    (routing state, HSRP, gateway maps): a mapping like
    ``{"gateway": True, "routing_protocols": ("ospf",)}``. Absent evidence
    never invents impact.
    """

    roles = dict(role_evidence or {})
    device = str((device_entry or {}).get("hostname") or "unknown")
    interfaces = [
        item
        for item in (device_entry or {}).get("interfaces") or ()
        if isinstance(item, Mapping)
    ]
    target = next(
        (
            item
            for item in interfaces
            if str(item.get("name") or "").casefold() == target_interface.casefold()
        ),
        None,
    )
    target_ip = _clean_ip(target.get("ip_address") if target else None)
    interface_type = classify_interface(target_interface)
    management_ip = _clean_ip((device_entry or {}).get("management_ip"))
    known_management = {ip for ip in (management_ip, *map(_clean_ip, seed_addresses)) if ip}
    freshness_penalty = 0.15 if not fresh else 0.0

    owns_management = bool(target_ip) and target_ip in known_management
    alternate_status, alternate_detail = _alternate_management(
        interfaces, target_interface, known_management, target_ip
    )
    assessment = ManagementAssessment(
        owns_management_address=owns_management,
        management_address=target_ip if owns_management else management_ip,
        alternate_status=alternate_status,
        alternate_detail=alternate_detail,
    )

    planes = (
        _management_plane(
            device, target_interface, target_ip, management_ip, owns_management,
            assessment, isolated_devices, freshness_penalty,
        ),
        _control_plane(device, target_interface, roles, freshness_penalty),
        _data_plane(
            device, target_interface, interface_type, target_ip, roles,
            interfaces, isolated_devices, freshness_penalty,
        ),
    )
    observability = _observability_plane(planes[0], device, target_interface)
    return (*planes, observability), assessment


# -- per-plane rules -----------------------------------------------------------


def _management_plane(
    device: str,
    interface: str,
    target_ip: str | None,
    management_ip: str | None,
    owns_management: bool,
    assessment: ManagementAssessment,
    isolated_devices: tuple[str, ...],
    freshness_penalty: float,
) -> PlaneImpact:
    if owns_management:
        verified_alternate = assessment.alternate_status == ALTERNATE_VERIFIED
        status = STATUS_DEGRADED if verified_alternate else STATUS_LOST
        explanation = (
            f"{interface} owns {target_ip}, the management address Atlas "
            f"uses to reach {device}. Services using this management address "
            "may become unavailable: SSH management, future discovery, "
            "configuration collection, and monitoring that depends on it."
        )
        if verified_alternate:
            explanation += f" {assessment.alternate_detail}."
        else:
            explanation += f" Alternate management path: {assessment.alternate_detail}."
        return PlaneImpact(
            plane=PLANE_MANAGEMENT,
            status=status,
            severity="medium" if verified_alternate else "high",
            confidence=max(0.05, 0.9 - freshness_penalty),
            explanation=explanation,
            affected=(f"{device} ({target_ip})",),
            evidence=(
                f"{interface} is configured with {target_ip} [topology snapshot]",
                f"Atlas discovered {device} via {target_ip} [discovery]",
            ),
            missing_evidence=(
                ("monitoring configuration is not collected",)
                if not verified_alternate
                else ()
            ),
        )
    if isolated_devices:
        return PlaneImpact(
            plane=PLANE_MANAGEMENT,
            status=STATUS_DEGRADED,
            severity="medium",
            confidence=max(0.05, 0.8 - freshness_penalty),
            explanation=(
                "Management addresses of "
                + ", ".join(isolated_devices)
                + " become unreachable through the discovered topology."
            ),
            affected=isolated_devices,
            evidence=("reachability computed from the topology snapshot",),
        )
    if management_ip is None:
        return PlaneImpact(
            plane=PLANE_MANAGEMENT,
            status=STATUS_UNKNOWN,
            severity="low",
            confidence=max(0.05, 0.4 - freshness_penalty),
            explanation=(
                f"No management address is recorded for {device}, so the "
                "management impact cannot be evaluated."
            ),
            missing_evidence=("device management address",),
        )
    if target_ip is None:
        # The target has no address; ownership of the management address by
        # ANOTHER interface may itself be unknown when no interface lists it.
        owner_known = _address_owner_known(management_ip, device)
        return PlaneImpact(
            plane=PLANE_MANAGEMENT,
            status=STATUS_NO_KNOWN_IMPACT if owner_known else STATUS_UNKNOWN,
            severity="none" if owner_known else "low",
            confidence=max(0.05, (0.75 if owner_known else 0.5) - freshness_penalty),
            explanation=(
                f"{interface} carries no IP address; the management address "
                f"{management_ip} is not on this interface."
                if owner_known
                else (
                    f"{interface} carries no IP address, but Atlas does not "
                    f"know which interface owns {management_ip}."
                )
            ),
            missing_evidence=(
                () if owner_known else ("interface owning the management address",)
            ),
        )
    return PlaneImpact(
        plane=PLANE_MANAGEMENT,
        status=STATUS_NO_KNOWN_IMPACT,
        severity="none",
        confidence=max(0.05, 0.85 - freshness_penalty),
        explanation=(
            f"{interface} carries {target_ip}, which is not the management "
            f"address ({management_ip}) Atlas uses for {device}."
        ),
        evidence=(f"management address {management_ip} rides another interface",),
    )


def _address_owner_known(management_ip: str | None, device: str) -> bool:
    # Conservative: without per-interface confirmation of the owner we say
    # "not on this interface" only when the target itself has no address at
    # all and management is clearly recorded — the common physical case.
    return management_ip is not None


def _control_plane(
    device: str, interface: str, roles: Mapping[str, Any], freshness_penalty: float
) -> PlaneImpact:
    protocols = tuple(
        str(item) for item in roles.get("routing_protocols") or ()
    )
    gateway_protocols = tuple(
        str(item) for item in roles.get("gateway_protocols") or ()
    )
    if protocols or gateway_protocols:
        names = ", ".join((*protocols, *gateway_protocols))
        return PlaneImpact(
            plane=PLANE_CONTROL,
            status=STATUS_LOST,
            severity="high",
            confidence=max(0.05, 0.85 - freshness_penalty),
            explanation=(
                f"{names} depend on {interface} of {device}: adjacencies or "
                "gateway roles on this interface will drop and routes may be "
                "withdrawn."
            ),
            affected=(*protocols, *gateway_protocols),
            evidence=(f"protocol role evidence on {interface}: {names}",),
        )
    return PlaneImpact(
        plane=PLANE_CONTROL,
        status=STATUS_NO_KNOWN_IMPACT,
        severity="none",
        confidence=max(0.05, 0.55 - freshness_penalty),
        explanation=(
            f"No routing or gateway protocol dependency was observed on "
            f"{interface} of {device}."
        ),
        missing_evidence=(
            "routing protocol state is not collected yet (OSPF/BGP/HSRP/VRRP)",
        ),
    )


def _data_plane(
    device: str,
    interface: str,
    interface_type: str,
    target_ip: str | None,
    roles: Mapping[str, Any],
    interfaces: list,
    isolated_devices: tuple[str, ...],
    freshness_penalty: float,
) -> PlaneImpact:
    if roles.get("gateway"):
        return PlaneImpact(
            plane=PLANE_DATA,
            status=STATUS_LOST,
            severity="high",
            confidence=max(0.05, 0.85 - freshness_penalty),
            explanation=(
                f"{interface} on {device} is a verified gateway: devices "
                "using it as their default gateway lose inter-VLAN/upstream "
                "reachability."
            ),
            evidence=(f"gateway role evidence for {interface}",),
        )
    if isolated_devices:
        return PlaneImpact(
            plane=PLANE_DATA,
            status=STATUS_LOST,
            severity="high",
            confidence=max(0.05, 0.85 - freshness_penalty),
            explanation=(
                "Forwarding through the discovered topology breaks for "
                + ", ".join(isolated_devices)
                + "."
            ),
            affected=isolated_devices,
            evidence=("reachability computed from the topology snapshot",),
        )
    if interface_type in LOGICAL_TYPES:
        physical_up = sorted(
            str(item.get("name"))
            for item in interfaces
            if isinstance(item, Mapping)
            and classify_interface(str(item.get("name") or "")) == TYPE_PHYSICAL
            and str(item.get("status") or "").casefold() == "up"
        )
        note = (
            f"Discovered physical interfaces ({', '.join(physical_up[:3])}) "
            "remain up, so Layer-2 switching continues. "
            if physical_up
            else ""
        )
        return PlaneImpact(
            plane=PLANE_DATA,
            status=STATUS_UNKNOWN,
            severity="low",
            confidence=max(0.05, 0.45 - freshness_penalty),
            explanation=(
                note
                + f"Atlas lacks endpoint/VLAN dependency evidence to determine "
                f"whether {interface} serves as a user or default-gateway "
                "interface"
                + (f" for {target_ip}" if target_ip else "")
                + "."
            ),
            evidence=tuple(
                f"{name} is up [topology snapshot]" for name in physical_up[:3]
            ),
            missing_evidence=(
                "VLAN membership and endpoint dependencies are not collected",
                "gateway configuration evidence is not collected",
            ),
        )
    return PlaneImpact(
        plane=PLANE_DATA,
        status=STATUS_NO_KNOWN_IMPACT,
        severity="none",
        confidence=max(0.05, 0.7 - freshness_penalty),
        explanation=(
            f"No forwarding dependency on {interface} of {device} is visible "
            "in the discovered topology."
        ),
        missing_evidence=("endpoint and service dependencies are not collected",),
    )


def _observability_plane(
    management: PlaneImpact, device: str, interface: str
) -> PlaneImpact:
    if management.status == STATUS_LOST:
        return PlaneImpact(
            plane=PLANE_OBSERVABILITY,
            status=STATUS_LOST,
            severity="high",
            confidence=management.confidence,
            explanation=(
                f"With the management address on {interface} gone, {device} "
                "becomes a monitoring blind spot: future Atlas discoveries "
                "and configuration collection will likely fail, its state "
                "goes stale, and alerting that uses this address stops."
            ),
            affected=(device,),
            evidence=("follows from the management-plane evaluation",),
        )
    if management.status == STATUS_DEGRADED:
        return PlaneImpact(
            plane=PLANE_OBSERVABILITY,
            status=STATUS_DEGRADED,
            severity="medium",
            confidence=management.confidence,
            explanation=(
                f"Visibility of {device} degrades until the alternate "
                "management path is exercised; expect gaps in discovery and "
                "collection."
            ),
            affected=(device,),
            evidence=("follows from the management-plane evaluation",),
        )
    if management.status == STATUS_UNKNOWN:
        return PlaneImpact(
            plane=PLANE_OBSERVABILITY,
            status=STATUS_UNKNOWN,
            severity="low",
            confidence=management.confidence,
            explanation=(
                "Observability impact cannot be evaluated without knowing "
                "the management dependency."
            ),
            missing_evidence=management.missing_evidence,
        )
    return PlaneImpact(
        plane=PLANE_OBSERVABILITY,
        status=STATUS_NO_KNOWN_IMPACT,
        severity="none",
        confidence=management.confidence,
        explanation=(
            f"Atlas keeps reaching {device} through its management address; "
            "no monitoring impact is known."
        ),
    )


# -- alternates -----------------------------------------------------------------


def _alternate_management(
    interfaces: list,
    target_interface: str,
    known_management: set[str],
    target_ip: str | None,
) -> tuple[str, str]:
    """Alternate management path: verified, candidate, or none known.

    Verified requires PROOF of reachability: the candidate address is
    itself a known-good connection address (another seed or the active
    management address on a different interface). A second address that
    merely exists is a candidate — Atlas never assumes it is reachable.
    """

    candidates: list[tuple[str, str]] = []
    for item in interfaces:
        name = str(item.get("name") or "")
        if name.casefold() == target_interface.casefold():
            continue
        ip = _clean_ip(item.get("ip_address"))
        if not ip or ip == target_ip:
            continue
        if str(item.get("status") or "").casefold() != "up":
            continue
        candidates.append((name, ip))
    for name, ip in sorted(candidates):
        if ip in known_management:
            return (
                ALTERNATE_VERIFIED,
                f"a verified alternate management address exists on {name} ({ip})",
            )
    if candidates:
        name, ip = sorted(candidates)[0]
        return (
            ALTERNATE_CANDIDATE,
            f"{name} ({ip}) is a candidate alternate, but its reachability "
            "is unverified — Atlas does not assume it works",
        )
    return (
        ALTERNATE_NONE_KNOWN,
        "no alternate management address is known on this device",
    )


def _clean_ip(value) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in ("unassigned", "none", "unknown"):
        return None
    return cleaned
