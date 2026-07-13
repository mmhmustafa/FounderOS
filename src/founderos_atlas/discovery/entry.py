"""Enterprise discovery entry methods (PR-043.2, codename DISCOVERY MODES).

Real engineers rarely start from a single seed. Atlas supports four
deterministic entry methods, all resolving to the SAME thing the
multihop engine already consumes — a set of seed candidate addresses —
so discovery keeps producing canonical enterprise models and every
downstream engine is untouched:

    1. Single seed device      — recursive discovery (unchanged)
    2. Management network       — a CIDR expanded into candidates
    3. Multiple seed devices    — several starting addresses
    4. Import device list       — a CSV of hostname / IP / platform / site

Every candidate carries its source, confidence, status, and reason;
CIDR expansion excludes network/broadcast/user addresses; large ranges
are gated by explicit safety rules. Nothing here connects to a device
or holds a secret — resolution is pure and testable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO
from ipaddress import ip_address, ip_network
from typing import Any


MODE_SEED = "seed"
MODE_SUBNET = "management-network"
MODE_MULTI_SEED = "multiple-seeds"
MODE_CSV = "import-list"
DISCOVERY_MODES = (MODE_SEED, MODE_SUBNET, MODE_MULTI_SEED, MODE_CSV)

# Candidate lifecycle states (spec vocabulary).
CANDIDATE_QUEUED = "queued"
CANDIDATE_CONNECTING = "connecting"
CANDIDATE_AUTHENTICATED = "authenticated"
CANDIDATE_UNSUPPORTED = "unsupported-platform"
CANDIDATE_AUTH_FAILED = "authentication-failed"
CANDIDATE_UNREACHABLE = "unreachable"
CANDIDATE_DISCOVERED = "discovered"
CANDIDATE_SKIPPED = "skipped"

# Candidate sources — where an address came from (evidence provenance).
SOURCE_SEED = "user-seed"
SOURCE_SUBNET = "management-network"
SOURCE_CSV = "imported-list"

# Discovery policies: how much evidence to collect per device.
POLICY_FAST = "fast"
POLICY_BALANCED = "balanced"
POLICY_DEEP = "deep"
DISCOVERY_POLICIES = (POLICY_FAST, POLICY_BALANCED, POLICY_DEEP)

# CIDR safety thresholds (usable-host counts), aligned to prefix sizes:
# /23 (510) ok · /22 (1022) warn · /18 (16382) confirm · /13+ reject.
SAFETY_WARN_HOSTS = 512         # a /22 and larger: warn
SAFETY_CONFIRM_HOSTS = 8192     # a /18 and larger: require confirmation
SAFETY_REJECT_HOSTS = 262144    # a /13 and larger: reject without override


@dataclass(frozen=True)
class DiscoveryCandidate:
    """One address Atlas may attempt, with its provenance and state."""

    address: str
    source: str
    confidence: str            # high | medium | low
    status: str = CANDIDATE_QUEUED
    reason: str = ""
    hostname: str | None = None
    platform_hint: str | None = None
    site_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            "reason": self.reason,
            "hostname": self.hostname,
            "platform_hint": self.platform_hint,
            "site_hint": self.site_hint,
        }


@dataclass(frozen=True)
class SafetyAssessment:
    """The gate before an expensive scan: count and required action."""

    candidate_count: int
    level: str                 # ok | warn | confirm | reject
    message: str

    @property
    def allowed(self) -> bool:
        return self.level != "reject"

    @property
    def needs_confirmation(self) -> bool:
        return self.level in ("confirm", "reject")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "level": self.level,
            "message": self.message,
            "allowed": self.allowed,
            "needs_confirmation": self.needs_confirmation,
        }


# -- CIDR expansion --------------------------------------------------------------


def _valid_ip(value: str) -> str | None:
    try:
        return str(ip_address(str(value).strip()))
    except (ValueError, TypeError):
        return None


def estimate_candidate_count(cidr: str) -> int:
    """Usable host count for a CIDR (network/broadcast excluded for IPv4)."""

    network = ip_network(str(cidr).strip(), strict=False)
    if network.version == 4 and network.prefixlen < 31:
        return max(0, network.num_addresses - 2)
    return network.num_addresses


def assess_scan_safety(cidr: str) -> SafetyAssessment:
    """Deterministic safety gate for a management-network scan."""

    count = estimate_candidate_count(cidr)
    if count > SAFETY_REJECT_HOSTS:
        return SafetyAssessment(
            count, "reject",
            f"{count} candidate addresses exceeds the safe limit "
            f"({SAFETY_REJECT_HOSTS}). Narrow the range, or split it — "
            "Atlas will not scan a range this large without an explicit "
            "override.",
        )
    if count >= SAFETY_CONFIRM_HOSTS:
        return SafetyAssessment(
            count, "confirm",
            f"{count} candidate addresses is a large scan. Confirm before "
            "starting — this attempts SSH to every usable address.",
        )
    if count >= SAFETY_WARN_HOSTS:
        return SafetyAssessment(
            count, "warn",
            f"{count} candidate addresses. This is a sizeable scan; review "
            "the estimate before starting.",
        )
    return SafetyAssessment(
        count, "ok", f"{count} candidate address(es) to attempt."
    )


def expand_management_network(
    cidr: str, *, exclusions: tuple[str, ...] = ()
) -> tuple[DiscoveryCandidate, ...]:
    """Expand a CIDR into deterministic, deduplicated SSH candidates.

    The network and broadcast addresses are always excluded (IPv4,
    prefix < 31), along with any user exclusions (addresses or nested
    CIDRs). Candidates are returned in ascending address order.
    """

    network = ip_network(str(cidr).strip(), strict=False)
    excluded: set[str] = set()
    excluded_networks = []
    for item in exclusions:
        cleaned = str(item).strip()
        if not cleaned:
            continue
        single = _valid_ip(cleaned)
        if single is not None:
            excluded.add(single)
            continue
        try:
            excluded_networks.append(ip_network(cleaned, strict=False))
        except ValueError:
            continue  # ignore malformed exclusions rather than fail
    hosts = (
        network.hosts()
        if network.version == 4 and network.prefixlen < 31
        else network
    )
    candidates: list[DiscoveryCandidate] = []
    for host in hosts:
        address = str(host)
        if address in excluded:
            continue
        if any(host in net for net in excluded_networks):
            continue
        candidates.append(
            DiscoveryCandidate(
                address=address,
                source=SOURCE_SUBNET,
                confidence="low",  # a subnet member is only a candidate
                reason=f"member of {network.with_prefixlen}",
            )
        )
    return tuple(candidates)


# -- CSV import ------------------------------------------------------------------


def parse_device_csv(text: str) -> tuple[tuple[DiscoveryCandidate, ...], tuple[str, ...]]:
    """Parse an imported device list into candidates plus honest warnings.

    Recognized columns (case-insensitive, any order): hostname,
    management_ip / ip / address, platform, site. Rows without a valid
    management address are skipped with a stated reason — never guessed.
    """

    warnings: list[str] = []
    candidates: list[DiscoveryCandidate] = []
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        return (), ("the imported list is empty",)
    field_map = {
        (name or "").strip().casefold(): name for name in reader.fieldnames
    }

    def column(row: dict, *names: str) -> str:
        for name in names:
            key = field_map.get(name)
            if key is not None and str(row.get(key) or "").strip():
                return str(row[key]).strip()
        return ""

    seen: set[str] = set()
    for index, row in enumerate(reader, start=2):  # row 1 is the header
        address = _valid_ip(
            column(row, "management_ip", "management ip", "ip", "address")
        )
        hostname = column(row, "hostname", "name") or None
        if address is None:
            label = hostname or f"row {index}"
            warnings.append(
                f"{label}: no valid management IP — skipped (Atlas never "
                "guesses an address)."
            )
            continue
        if address in seen:
            warnings.append(f"{address}: duplicate row ignored.")
            continue
        seen.add(address)
        candidates.append(
            DiscoveryCandidate(
                address=address,
                source=SOURCE_CSV,
                confidence="high",  # an operator-provided inventory address
                reason="from imported device list",
                hostname=hostname,
                platform_hint=column(row, "platform", "os") or None,
                site_hint=column(row, "site", "location") or None,
            )
        )
    return tuple(candidates), tuple(warnings)


# -- the resolved plan -----------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryPlan:
    """A resolved, deterministic discovery request — any mode, one shape."""

    mode: str
    candidates: tuple[DiscoveryCandidate, ...]
    policy: str = POLICY_BALANCED
    max_depth: int = 1
    max_devices: int = 64
    timeout_seconds: int = 15
    concurrency: int = 1
    exclusions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def seed_addresses(self) -> tuple[str, ...]:
        return tuple(candidate.address for candidate in self.candidates)

    @property
    def collect_configuration(self) -> bool:
        return self.policy == POLICY_DEEP

    @property
    def effective_depth(self) -> int:
        # Subnet and CSV scans enumerate the estate directly; recursion
        # off them would re-scan the same devices, so Fast pins depth 0.
        if self.policy == POLICY_FAST:
            return 0
        return self.max_depth

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "policy": self.policy,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "max_depth": self.max_depth,
            "effective_depth": self.effective_depth,
            "max_devices": self.max_devices,
            "timeout_seconds": self.timeout_seconds,
            "concurrency": self.concurrency,
            "collect_configuration": self.collect_configuration,
            "exclusions": list(self.exclusions),
            "warnings": list(self.warnings),
            "attributes": dict(self.attributes),
        }


def classify_candidate_outcomes(
    plan: DiscoveryPlan,
    visits: tuple[tuple[str, str, str], ...],
    *,
    completed_addresses: frozenset[str] = frozenset(),
) -> tuple[DiscoveryCandidate, ...]:
    """Map traversal visits back onto plan candidates, deterministically.

    ``visits`` are ``(host, status, detail)`` triples from the multihop
    report (status: connected | skipped | failed). Each candidate gets a
    lifecycle status and a stated reason. Addresses already discovered in
    a prior run (``completed_addresses``, for resume) are reported as
    discovered without being re-attempted.
    """

    by_host: dict[str, tuple[str, str]] = {}
    for host, status, detail in visits:
        # The first meaningful visit for a host wins (connected beats a
        # later skip of the same address).
        if host not in by_host or status == "connected":
            by_host[host] = (status, detail)

    resolved: list[DiscoveryCandidate] = []
    for candidate in plan.candidates:
        if candidate.address in completed_addresses:
            resolved.append(
                _with(candidate, CANDIDATE_DISCOVERED,
                      "already discovered in an earlier run (cached)")
            )
            continue
        visit = by_host.get(candidate.address)
        if visit is None:
            resolved.append(
                _with(candidate, CANDIDATE_QUEUED, "not yet attempted")
            )
            continue
        status, detail = visit
        if status == "connected":
            resolved.append(
                _with(candidate, CANDIDATE_DISCOVERED, detail or "discovered")
            )
        elif status == "skipped":
            resolved.append(_with(candidate, CANDIDATE_SKIPPED, detail))
        else:  # failed
            folded = detail.casefold()
            if "unsupported platform" in folded:
                resolved.append(
                    _with(candidate, CANDIDATE_UNSUPPORTED, detail)
                )
            elif any(
                token in folded
                for token in ("auth", "password", "credential", "permission")
            ):
                resolved.append(
                    _with(candidate, CANDIDATE_AUTH_FAILED, detail)
                )
            else:
                resolved.append(
                    _with(candidate, CANDIDATE_UNREACHABLE, detail)
                )
    return tuple(resolved)


def summarize_candidates(candidates: tuple[DiscoveryCandidate, ...]) -> dict[str, Any]:
    """Honest discovery-summary counts by candidate outcome."""

    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.status] = counts.get(candidate.status, 0) + 1
    reachable = sum(
        counts.get(state, 0)
        for state in (
            CANDIDATE_DISCOVERED, CANDIDATE_AUTH_FAILED, CANDIDATE_UNSUPPORTED
        )
    )
    return {
        "candidate_addresses": len(candidates),
        "ssh_reachable": reachable,
        "authenticated": counts.get(CANDIDATE_DISCOVERED, 0)
        + counts.get(CANDIDATE_UNSUPPORTED, 0),
        "discovered": counts.get(CANDIDATE_DISCOVERED, 0),
        "unsupported_platforms": counts.get(CANDIDATE_UNSUPPORTED, 0),
        "authentication_failed": counts.get(CANDIDATE_AUTH_FAILED, 0),
        "unreachable": counts.get(CANDIDATE_UNREACHABLE, 0),
        "skipped": counts.get(CANDIDATE_SKIPPED, 0),
        "by_status": dict(sorted(counts.items())),
    }


def _with(candidate: DiscoveryCandidate, status: str, reason: str) -> DiscoveryCandidate:
    from dataclasses import replace

    return replace(candidate, status=status, reason=reason or candidate.reason)


class DiscoveryPlanError(ValueError):
    """A resolution problem the operator must fix (bad mode/input/limit)."""


def resolve_plan(
    mode: str,
    *,
    seed: str | None = None,
    seeds: tuple[str, ...] = (),
    cidr: str | None = None,
    csv_text: str | None = None,
    policy: str = POLICY_BALANCED,
    max_depth: int = 1,
    max_devices: int = 64,
    timeout_seconds: int = 15,
    concurrency: int = 1,
    exclusions: tuple[str, ...] = (),
    allow_large_scan: bool = False,
) -> DiscoveryPlan:
    """Resolve any entry method into one deterministic ``DiscoveryPlan``."""

    if mode not in DISCOVERY_MODES:
        raise DiscoveryPlanError(f"unknown discovery mode: {mode!r}")
    if policy not in DISCOVERY_POLICIES:
        raise DiscoveryPlanError(f"unknown discovery policy: {policy!r}")
    warnings: list[str] = []
    attributes: dict[str, Any] = {}

    if mode == MODE_SEED:
        address = _valid_ip(seed or "")
        if address is None:
            raise DiscoveryPlanError("a valid seed address is required")
        candidates = (
            DiscoveryCandidate(
                address, SOURCE_SEED, "high", reason="user-provided seed"
            ),
        )
    elif mode == MODE_MULTI_SEED:
        addresses: list[str] = []
        for value in (seed, *seeds):
            cleaned = _valid_ip(value or "")
            if cleaned and cleaned not in addresses:
                addresses.append(cleaned)
            elif value and cleaned is None:
                warnings.append(f"ignored invalid seed {value!r}")
        if not addresses:
            raise DiscoveryPlanError("at least one valid seed is required")
        candidates = tuple(
            DiscoveryCandidate(
                address, SOURCE_SEED, "high", reason="user-provided seed"
            )
            for address in addresses
        )
    elif mode == MODE_SUBNET:
        if not cidr:
            raise DiscoveryPlanError("a management network CIDR is required")
        safety = assess_scan_safety(cidr)
        attributes["safety"] = safety.to_dict()
        if not safety.allowed and not allow_large_scan:
            raise DiscoveryPlanError(safety.message)
        if safety.needs_confirmation and not allow_large_scan:
            raise DiscoveryPlanError(
                safety.message + " Re-submit with an explicit override to "
                "proceed."
            )
        candidates = expand_management_network(
            cidr, exclusions=tuple(exclusions)
        )
        if not candidates:
            raise DiscoveryPlanError(
                "the CIDR expanded to zero candidates after exclusions"
            )
        # A subnet scan must be able to hold every candidate it finds.
        max_devices = max(max_devices, len(candidates))
        attributes["cidr"] = ip_network(str(cidr).strip(), strict=False).with_prefixlen
    else:  # MODE_CSV
        if not csv_text or not csv_text.strip():
            raise DiscoveryPlanError("an imported device list is required")
        candidates, csv_warnings = parse_device_csv(csv_text)
        warnings.extend(csv_warnings)
        if not candidates:
            raise DiscoveryPlanError(
                "the imported list contained no usable device addresses"
            )
        max_devices = max(max_devices, len(candidates))

    return DiscoveryPlan(
        mode=mode,
        candidates=candidates,
        policy=policy,
        max_depth=max_depth,
        max_devices=max_devices,
        timeout_seconds=timeout_seconds,
        concurrency=concurrency,
        exclusions=tuple(exclusions),
        warnings=tuple(warnings),
        attributes=attributes,
    )
