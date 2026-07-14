"""Network Identity & Scope (PR-043.9, IDENTITY).

Atlas distinguishes three layers:

    Enterprise  →  Network  →  Discovery Profile

A **Network** is a logical enterprise environment — it owns topology,
history, changes, predictions, health, and incidents. A **Discovery
Profile** is only an *observation point* — it owns credentials, a
discovery method (seed / CIDR / import), a schedule, and observation
metadata. Two profiles that observe the same environment belong to one
Network; the same physical estate scanned twice is not two networks.

Network identity is derived **only from technical evidence** — canonical
device serial numbers, router IDs, loopback addresses, management
addresses, seed addresses, and topology — and **never from the profile
name**. Two profiles named "Delhi lab" and "Delhi lab1" that share
serials and router IDs are the same network; two profiles both named
"core" that share no evidence are not.

This module computes fingerprints and similarity. It never merges
networks automatically (Part 3): it surfaces duplicate *candidates* with
a similarity score and the evidence behind it, for the operator to keep
separate or merge later.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any


_UNKNOWN = frozenset({"", "unknown", "none", "-"})
_LOOPBACK_NAME = re.compile(r"^(lo|loopback)", re.IGNORECASE)

# Evidence weights for similarity (Part 3). Strong hardware identity
# (serials) dominates; identifiers derived from configuration (router IDs,
# loopbacks) are strong; addresses are medium; hostnames are weak because
# enterprises reuse them. Weights are relative, not absolute.
_EVIDENCE_WEIGHTS = {
    "serials": 0.34,
    "router_ids": 0.20,
    "loopbacks": 0.16,
    "management_ips": 0.14,
    "seeds": 0.08,
    "interface_ips": 0.05,
    "hostnames": 0.03,
}

# A pair at or above this similarity is surfaced as a duplicate candidate.
DUPLICATE_THRESHOLD = 70


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and cleaned.casefold() not in _UNKNOWN else None


@dataclass(frozen=True)
class NetworkFingerprint:
    """The normalized technical evidence that identifies one network.

    Every field is a set of casefolded evidence tokens extracted from a
    topology snapshot — never a name. Two fingerprints are compared by
    weighted overlap of these sets.
    """

    serials: frozenset[str] = frozenset()
    router_ids: frozenset[str] = frozenset()
    loopbacks: frozenset[str] = frozenset()
    management_ips: frozenset[str] = frozenset()
    seeds: frozenset[str] = frozenset()
    interface_ips: frozenset[str] = frozenset()
    hostnames: frozenset[str] = frozenset()
    device_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not (
            self.serials or self.router_ids or self.loopbacks
            or self.management_ips or self.seeds
        )

    def _sets(self) -> dict[str, frozenset[str]]:
        return {
            "serials": self.serials,
            "router_ids": self.router_ids,
            "loopbacks": self.loopbacks,
            "management_ips": self.management_ips,
            "seeds": self.seeds,
            "interface_ips": self.interface_ips,
            "hostnames": self.hostnames,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "serials": sorted(self.serials),
            "router_ids": sorted(self.router_ids),
            "loopbacks": sorted(self.loopbacks),
            "management_ips": sorted(self.management_ips),
            "seeds": sorted(self.seeds),
            "interface_ips": sorted(self.interface_ips),
            "hostnames": sorted(self.hostnames),
            "device_count": self.device_count,
        }


def fingerprint_snapshot(
    snapshot: Mapping[str, Any] | None,
    *,
    seeds: tuple[str, ...] = (),
) -> NetworkFingerprint:
    """Extract a network fingerprint from a topology snapshot (the
    Enterprise Knowledge Graph) plus the profile's declared seed(s).

    Only normalized evidence is used: serials, router IDs (device
    metadata + the address-ownership index's router-id claims), loopback
    interface addresses, management addresses, interface addresses, and
    hostnames. The profile name is deliberately ignored.
    """

    serials: set[str] = set()
    router_ids: set[str] = set()
    loopbacks: set[str] = set()
    management_ips: set[str] = set()
    interface_ips: set[str] = set()
    hostnames: set[str] = set()
    device_count = 0

    data = dict(snapshot or {})
    for device in data.get("devices") or ():
        if not isinstance(device, Mapping):
            continue
        device_count += 1
        serial = _clean(device.get("serial_number"))
        if serial:
            serials.add(serial.casefold())
        management = _clean(device.get("management_ip"))
        if management:
            management_ips.add(management.casefold())
        hostname = _clean(device.get("hostname"))
        if hostname:
            hostnames.add(hostname.casefold())
        metadata = dict(device.get("metadata") or {})
        for key in ("router_id", "bgp_router_id", "ospf_router_id"):
            router_id = _clean(metadata.get(key))
            if router_id:
                router_ids.add(router_id.casefold())
        for interface in device.get("interfaces") or ():
            if not isinstance(interface, Mapping):
                continue
            address = _clean(interface.get("ip_address"))
            if not address:
                continue
            interface_ips.add(address.casefold())
            if _LOOPBACK_NAME.match(str(interface.get("name") or "")):
                loopbacks.add(address.casefold())

    # The address-ownership index (Evidence Correlation) records router-id
    # claims explicitly — fold them in.
    ownership = (data.get("metadata") or {}).get("address_ownership") or {}
    for address, claim in ownership.items() if isinstance(ownership, Mapping) else ():
        if isinstance(claim, Mapping) and str(claim.get("kind")) == "router-id":
            cleaned = _clean(address)
            if cleaned:
                router_ids.add(cleaned.casefold())

    seed_set = {
        _clean(seed).casefold() for seed in seeds if _clean(seed)
    }
    return NetworkFingerprint(
        serials=frozenset(serials),
        router_ids=frozenset(router_ids),
        loopbacks=frozenset(loopbacks),
        management_ips=frozenset(management_ips),
        seeds=frozenset(seed_set),
        interface_ips=frozenset(interface_ips),
        hostnames=frozenset(hostnames),
        device_count=device_count,
    )


@dataclass(frozen=True)
class SimilarityResult:
    """How alike two network fingerprints are, and why."""

    score: int  # 0–100
    reasons: tuple[str, ...]
    shared_evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def is_duplicate_candidate(self) -> bool:
        return self.score >= DUPLICATE_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reasons": list(self.reasons),
            "shared_evidence": {
                key: list(value) for key, value in self.shared_evidence.items()
            },
        }


_REASON_LABEL = {
    "serials": "same serial number(s)",
    "router_ids": "same router ID(s)",
    "loopbacks": "same loopback address(es)",
    "management_ips": "same management address(es)",
    "seeds": "same seed address(es)",
    "interface_ips": "same interface address(es)",
    "hostnames": "same hostname(s)",
}


def compare_fingerprints(
    left: NetworkFingerprint, right: NetworkFingerprint
) -> SimilarityResult:
    """Evidence-based similarity between two networks (0–100), with reasons.

    Each evidence dimension contributes its weighted Jaccard overlap; the
    score is the weighted sum over dimensions where BOTH sides have
    evidence (so an absent dimension neither helps nor hurts). Names are
    never consulted."""

    if left.is_empty or right.is_empty:
        return SimilarityResult(0, ())

    left_sets = left._sets()
    right_sets = right._sets()
    total_weight = 0.0
    accumulated = 0.0
    reasons: list[tuple[float, str]] = []
    shared: dict[str, tuple[str, ...]] = {}
    for key, weight in _EVIDENCE_WEIGHTS.items():
        a = left_sets[key]
        b = right_sets[key]
        if not a or not b:
            continue  # a dimension only counts when both sides observed it
        union = a | b
        intersection = a & b
        if not union:
            continue
        overlap = len(intersection) / len(union)
        total_weight += weight
        accumulated += weight * overlap
        if intersection:
            shared[key] = tuple(sorted(intersection))
            reasons.append((weight * overlap, _REASON_LABEL[key]))
    if total_weight == 0:
        return SimilarityResult(0, ())
    score = round(100 * accumulated / total_weight)
    # A shared chassis serial is globally-unique hardware identity: the same
    # physical device appears in both observations, so the pair is a strong
    # duplicate candidate even if addresses were re-mapped between scans.
    # (Router IDs are NOT floored — loopback-derived IDs legitimately
    # collide across separate labs.) The floor scales with serial overlap.
    shared_serials = left.serials & right.serials
    if shared_serials:
        serial_overlap = len(shared_serials) / len(left.serials | right.serials)
        score = max(score, round(70 + 25 * serial_overlap))
    ordered_reasons = tuple(
        label for _weight, label in sorted(reasons, key=lambda item: -item[0])
    )
    return SimilarityResult(
        score=score, reasons=ordered_reasons, shared_evidence=shared
    )


@dataclass(frozen=True)
class ObservationPoint:
    """One discovery profile as an observation point plus its fingerprint."""

    profile_id: str
    profile_name: str
    fingerprint: NetworkFingerprint
    archived: bool = False


@dataclass(frozen=True)
class DuplicateCandidate:
    """A likely-duplicate pair of observation points — never auto-merged."""

    left_profile_id: str
    left_profile_name: str
    right_profile_id: str
    right_profile_name: str
    similarity: SimilarityResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_profile_id": self.left_profile_id,
            "left_profile_name": self.left_profile_name,
            "right_profile_id": self.right_profile_id,
            "right_profile_name": self.right_profile_name,
            "score": self.similarity.score,
            "reasons": list(self.similarity.reasons),
            "shared_evidence": self.similarity.to_dict()["shared_evidence"],
            # Atlas never merges automatically. The operator keeps the
            # observation points separate or reviews the duplicate — an
            # explicit merge is future work (PR-043.9 Part 3 / PR-043.10
            # Part 6 wording).
            "actions": ["keep-separate", "review-duplicate"],
        }


@dataclass(frozen=True)
class Network:
    """A logical enterprise environment — one or more observation points
    that share technical identity."""

    network_id: str
    label: str
    profile_ids: tuple[str, ...]
    profile_names: tuple[str, ...]
    device_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "network_id": self.network_id,
            "label": self.label,
            "profile_ids": list(self.profile_ids),
            "profile_names": list(self.profile_names),
            "profile_count": len(self.profile_ids),
            "device_count": self.device_count,
        }


@dataclass(frozen=True)
class NetworkResolution:
    """The Enterprise → Network → Profile view derived from evidence."""

    networks: tuple[Network, ...]
    duplicate_candidates: tuple[DuplicateCandidate, ...]

    @property
    def network_count(self) -> int:
        return len(self.networks)

    @property
    def profile_count(self) -> int:
        return sum(len(network.profile_ids) for network in self.networks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "network_count": self.network_count,
            "profile_count": self.profile_count,
            "duplicate_candidate_count": len(self.duplicate_candidates),
            "networks": [network.to_dict() for network in self.networks],
            "duplicate_candidates": [
                candidate.to_dict() for candidate in self.duplicate_candidates
            ],
        }


def detect_duplicate_networks(
    observations: tuple[ObservationPoint, ...] | list[ObservationPoint],
) -> tuple[DuplicateCandidate, ...]:
    """Every profile pair whose evidence similarity is a duplicate
    candidate, strongest first. Deterministic; never merges."""

    points = [point for point in observations if not point.archived]
    candidates: list[DuplicateCandidate] = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            left, right = points[i], points[j]
            similarity = compare_fingerprints(left.fingerprint, right.fingerprint)
            if similarity.is_duplicate_candidate:
                candidates.append(
                    DuplicateCandidate(
                        left_profile_id=left.profile_id,
                        left_profile_name=left.profile_name,
                        right_profile_id=right.profile_id,
                        right_profile_name=right.profile_name,
                        similarity=similarity,
                    )
                )
    candidates.sort(
        key=lambda candidate: (
            -candidate.similarity.score,
            candidate.left_profile_id,
            candidate.right_profile_id,
        )
    )
    return tuple(candidates)


def resolve_networks(
    observations: tuple[ObservationPoint, ...] | list[ObservationPoint],
) -> NetworkResolution:
    """Cluster observation points into Networks by technical identity.

    Profiles whose fingerprints are duplicate candidates (>= threshold)
    are the SAME network; the rest are their own network. Clustering is a
    deterministic union-find over the evidence-similarity graph — the
    profile name is never used to group. Archived observation points do
    not form or join networks.
    """

    points = [point for point in observations if not point.archived]
    parents = list(range(len(points)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    duplicate_candidates = detect_duplicate_networks(points)
    index_by_id = {point.profile_id: i for i, point in enumerate(points)}
    for candidate in duplicate_candidates:
        i = index_by_id[candidate.left_profile_id]
        j = index_by_id[candidate.right_profile_id]
        parents[find(j)] = find(i)

    clusters: dict[int, list[int]] = {}
    for index in range(len(points)):
        clusters.setdefault(find(index), []).append(index)

    networks: list[Network] = []
    for root in sorted(clusters, key=lambda r: points[r].profile_id):
        members = [points[i] for i in clusters[root]]
        members.sort(key=lambda point: point.profile_id)
        # The network label is the earliest contributing profile's name —
        # a human handle only; identity remains evidence-based.
        primary = members[0]
        device_count = max(
            (member.fingerprint.device_count for member in members), default=0
        )
        networks.append(
            Network(
                network_id=f"net:{primary.profile_id}",
                label=primary.profile_name,
                profile_ids=tuple(member.profile_id for member in members),
                profile_names=tuple(member.profile_name for member in members),
                device_count=device_count,
            )
        )
    networks.sort(key=lambda network: network.label.casefold())
    return NetworkResolution(
        networks=tuple(networks),
        duplicate_candidates=duplicate_candidates,
    )
