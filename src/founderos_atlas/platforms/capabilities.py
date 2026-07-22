"""The production capability model (PR-049, POLYGLOT, Parts 2–3).

One vocabulary for what a platform can be asked, and one honest set of
outcomes for what happened when Atlas asked. Every Wave-1 driver reports
against this model; diagnostics, tests and documentation read it back.

The two distinctions the whole model exists to protect:

- **UNSUPPORTED is not FAILED.** A device that answers "unknown command" has
  answered. A transport that timed out has not. The first is a fact about the
  platform; the second is a fact about this attempt.
- **Empty is not failed.** A command that executed and returned nothing is a
  successful collection whose answer is "nothing".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- capability vocabulary (Part 3) ------------------------------------------

IDENTITY = "identity"
VERSION = "version"
INVENTORY = "inventory"
CONFIGURATION = "configuration"
INTERFACES = "interfaces"
INTERFACE_ADDRESSES = "interface-addresses"
INTERFACE_DESCRIPTIONS = "interface-descriptions"
ARP = "arp"
MAC_TABLE = "mac-table"
LLDP = "lldp"
CDP = "cdp"
BGP = "bgp"
OSPF = "ospf"
ROUTES = "routes"
STATIC_ROUTES = "static-routes"
# Policy-based routing: the rules consulted BEFORE the routing table. A
# separate capability from ROUTES because a device can answer one and not
# the other, and "no policy routing configured" must stay distinguishable
# from "Atlas never asked".
POLICY_ROUTES = "policy-routes"
VRF = "vrf"
VLAN = "vlan"
LAG = "lag"                      # port-channel / aggregated ethernet / MLAG
STP = "stp"
FIRST_HOP_REDUNDANCY = "first-hop-redundancy"
WEB_MANAGEMENT = "web-management"
API_MANAGEMENT = "api-management"

CAPABILITIES = (
    IDENTITY, VERSION, INVENTORY, CONFIGURATION, INTERFACES,
    INTERFACE_ADDRESSES, INTERFACE_DESCRIPTIONS, ARP, MAC_TABLE, LLDP, CDP,
    BGP, OSPF, ROUTES, STATIC_ROUTES, POLICY_ROUTES, VRF, VLAN, LAG, STP,
    FIRST_HOP_REDUNDANCY, WEB_MANAGEMENT, API_MANAGEMENT,
)

# -- outcomes (Part 3) --------------------------------------------------------

SUPPORTED = "supported"                           # executed, evidence produced
SUPPORTED_WITH_LIMITATIONS = "supported-with-limitations"
UNSUPPORTED = "unsupported"                       # the device said so
NOT_ATTEMPTED = "not-attempted"                   # excluded by plan/tier
FAILED = "failed"                                 # this attempt broke

STATUSES = (
    SUPPORTED, SUPPORTED_WITH_LIMITATIONS, UNSUPPORTED, NOT_ATTEMPTED, FAILED,
)

# Collection tiers (Part 22). A tier never silently reduces evidence — the
# active tier travels with the discovery and the skipped capabilities report
# NOT_ATTEMPTED, by name.
TIER_FAST = "fast"
TIER_STANDARD = "standard"
TIER_DEEP = "deep"
TIERS = (TIER_FAST, TIER_STANDARD, TIER_DEEP)
_TIER_RANK = {TIER_FAST: 0, TIER_STANDARD: 1, TIER_DEEP: 2}


def tier_includes(active: str, wanted: str) -> bool:
    return _TIER_RANK.get(active, 1) >= _TIER_RANK.get(wanted, 1)


# -- support maturity (Part 20) -----------------------------------------------

EXPERIMENTAL = "experimental"    # fixture-tested; incomplete coverage
BETA = "beta"                    # contract + transcript + live on one version
PRODUCTION = "production"        # live across versions, failure modes proven

MATURITY_LEVELS = (EXPERIMENTAL, BETA, PRODUCTION)


@dataclass(frozen=True)
class CommandSpec:
    """One capability's ordered way of being collected (Part 11).

    ``commands`` is primary-first: each is attempted only when the device
    rejected the one before it (an *exec* failure stops the chain — retrying
    a broken transport with a different spelling proves nothing). Which
    command finally answered, and why the earlier ones did not, is recorded —
    incompatibility is surfaced, never hidden.
    """

    capability: str
    commands: tuple[str, ...]
    required: bool = False
    tier: str = TIER_STANDARD
    limitation: str | None = None    # -> SUPPORTED_WITH_LIMITATIONS when set

    def __post_init__(self) -> None:
        if not self.commands:
            raise ValueError("a CommandSpec needs at least one command")


@dataclass(frozen=True)
class CapabilityReport:
    """What actually happened for one capability on one device."""

    capability: str
    status: str
    command_used: str | None = None
    commands_attempted: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "status": self.status,
            "command_used": self.command_used,
            "commands_attempted": list(self.commands_attempted),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DetectionResult:
    """Why a driver was (or was not) chosen (Part 4).

    ``confidence`` is deterministic — a fixed score per evidence kind, capped
    at 0.95 like every Atlas confidence. ``alternatives`` are other drivers
    whose matchers also accepted the probe, so a wrong pick is visible instead
    of silent.
    """

    platform_id: str | None
    driver: str | None
    confidence: float
    evidence: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    reason: str = ""
    overridden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "driver": self.driver,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "alternatives": list(self.alternatives),
            "reason": self.reason,
            "overridden": self.overridden,
        }


@dataclass
class DriverDiagnostics:
    """Per-device driver diagnostics (Part 16), carried in device metadata."""

    platform_id: str = ""
    driver: str = ""
    maturity: str = EXPERIMENTAL
    detection: dict[str, Any] = field(default_factory=dict)
    collection_tier: str = TIER_STANDARD
    reports: list[CapabilityReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        totals = {status: 0 for status in STATUSES}
        for report in self.reports:
            totals[report.status] = totals.get(report.status, 0) + 1
        return totals

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "driver": self.driver,
            "maturity": self.maturity,
            "detection": dict(self.detection),
            "collection_tier": self.collection_tier,
            "capabilities": [report.to_dict() for report in self.reports],
            "counts": self.counts(),
            "warnings": list(self.warnings),
        }
