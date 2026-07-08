"""Device identity resolution over Atlas discovery observations.

The resolver clusters device observations and neighbor references that
describe the same physical device, chooses one canonical hostname per
cluster, and can rewrite ``DiscoveryResult`` values so every downstream
layer (reconciliation, snapshot, viewer) sees exactly one identity per
device. Original observations are preserved as aliases and metadata.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from founderos_atlas.discovery.models import DiscoveryResult

from .canonical import (
    CanonicalDevice,
    DeviceIdentity,
    choose_primary_hostname,
    display_label,
    normalize_hostname,
)
from .matching import DEFAULT_MATCH_RULES, MatchRule


@dataclass(frozen=True)
class IdentityResolution:
    """Outcome of one resolution pass over a set of discovery results."""

    devices: tuple[CanonicalDevice, ...]
    observed_only: tuple[CanonicalDevice, ...]
    _display_by_key: dict[str, str]
    _aliases_by_display: dict[str, tuple[str, ...]]

    def display_hostname(self, hostname: str) -> str:
        """Canonical display name for any observed hostname or alias."""

        return self._display_by_key.get(normalize_hostname(hostname), hostname)

    def aliases_for(self, display_hostname: str) -> tuple[str, ...]:
        return self._aliases_by_display.get(normalize_hostname(display_hostname), ())

    def canonicalize(
        self, results: Iterable[DiscoveryResult]
    ) -> tuple[DiscoveryResult, ...]:
        """Rewrite results onto canonical hostnames; originals kept in metadata."""

        canonical_results: list[DiscoveryResult] = []
        for result in results:
            if not isinstance(result, DiscoveryResult):
                raise TypeError("results must contain only DiscoveryResult values")
            device = result.device
            display = self.display_hostname(device.hostname)
            aliases = self.aliases_for(display)
            if display != device.hostname or aliases:
                identity_metadata = {
                    "canonical_hostname": display,
                    "aliases": aliases,
                    "observed_hostname": device.hostname,
                }
                device = replace(
                    device,
                    hostname=display,
                    metadata={**dict(device.metadata), "identity": identity_metadata},
                )
            neighbors = []
            neighbors_changed = False
            for neighbor in result.neighbors:
                remote_display = self.display_hostname(neighbor.remote_hostname)
                if remote_display != neighbor.remote_hostname:
                    neighbors_changed = True
                    neighbor = replace(
                        neighbor,
                        remote_hostname=remote_display,
                        metadata={
                            **dict(neighbor.metadata),
                            "observed_remote_hostname": neighbor.remote_hostname,
                        },
                    )
                neighbors.append(neighbor)
            if device is not result.device or neighbors_changed:
                result = replace(result, device=device, neighbors=tuple(neighbors))
            canonical_results.append(result)
        return tuple(canonical_results)


class IdentityResolver:
    """Cluster observations into canonical devices using configurable rules."""

    def __init__(self, rules: Sequence[MatchRule] = DEFAULT_MATCH_RULES) -> None:
        rules = tuple(rules)
        if not rules or not all(isinstance(rule, MatchRule) for rule in rules):
            raise TypeError("rules must be a non-empty sequence of MatchRule values")
        self._rules = rules

    def resolve(self, results: Iterable[DiscoveryResult]) -> IdentityResolution:
        observations = tuple(results)
        if not all(isinstance(result, DiscoveryResult) for result in observations):
            raise TypeError("results must contain only DiscoveryResult values")

        device_identities = [
            DeviceIdentity.from_device(result.device) for result in observations
        ]
        device_clusters = self._cluster(device_identities)

        # Attach neighbor references to matching device clusters; the rest
        # cluster among themselves as observed-only (never connected) devices.
        references: list[DeviceIdentity] = []
        for result in observations:
            references.extend(
                DeviceIdentity.from_neighbor(neighbor) for neighbor in result.neighbors
            )
        unmatched: list[DeviceIdentity] = []
        for reference in references:
            merged = self._attach(reference, device_clusters)
            if not merged:
                unmatched.append(reference)
        observed_clusters = self._cluster(unmatched)

        devices = self._build_devices(device_clusters, observations)
        observed = self._build_observed(observed_clusters)
        display_by_key, aliases_by_display = _display_tables(devices + observed)
        return IdentityResolution(
            devices=devices,
            observed_only=observed,
            _display_by_key=display_by_key,
            _aliases_by_display=aliases_by_display,
        )

    def _matches(self, first: DeviceIdentity, second: DeviceIdentity) -> bool:
        return any(rule.matches(first, second) for rule in self._rules)

    def _cluster(
        self, identities: Sequence[DeviceIdentity]
    ) -> list[tuple[DeviceIdentity, tuple[int, ...]]]:
        """Union-find over identities; returns merged identity + member indexes."""

        parents = list(range(len(identities)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        for i in range(len(identities)):
            for j in range(i + 1, len(identities)):
                if find(i) != find(j) and self._matches(identities[i], identities[j]):
                    parents[find(j)] = find(i)

        grouped: dict[int, list[int]] = {}
        for index in range(len(identities)):
            grouped.setdefault(find(index), []).append(index)
        clusters = []
        for root in sorted(grouped):
            members = tuple(grouped[root])
            merged = identities[members[0]]
            for index in members[1:]:
                merged = merged.merged_with(identities[index])
            clusters.append((merged, members))
        return clusters

    def _attach(
        self,
        reference: DeviceIdentity,
        device_clusters: list[tuple[DeviceIdentity, tuple[int, ...]]],
    ) -> bool:
        for position, (merged, members) in enumerate(device_clusters):
            if self._matches(reference, merged):
                device_clusters[position] = (merged.merged_with(reference), members)
                return True
        return False

    def _build_devices(
        self,
        clusters: list[tuple[DeviceIdentity, tuple[int, ...]]],
        observations: tuple[DiscoveryResult, ...],
    ) -> tuple[CanonicalDevice, ...]:
        devices = []
        for merged, members in clusters:
            primary = choose_primary_hostname(merged.hostnames)
            first = observations[members[0]].device
            display = display_label(primary) if primary else first.management_ip
            devices.append(
                CanonicalDevice(
                    canonical_hostname=display,
                    aliases=_aliases(merged.hostnames, display),
                    management_ips=merged.management_ips,
                    vendor=first.vendor,
                    platform=first.platform,
                    os_name=first.os_name,
                    os_version=first.os_version,
                    serial_number=merged.serial_number,
                    device_ids=tuple(
                        observations[index].device.device_id for index in members
                    ),
                    sources=tuple(
                        identity_source
                        for index in members
                        for identity_source in (
                            f"discovered:{observations[index].device.device_id}",
                        )
                    ),
                    discovered=True,
                )
            )
        return tuple(devices)

    def _build_observed(
        self, clusters: list[tuple[DeviceIdentity, tuple[int, ...]]]
    ) -> tuple[CanonicalDevice, ...]:
        observed = []
        for merged, _ in clusters:
            primary = choose_primary_hostname(merged.hostnames)
            if primary is None:
                continue
            observed.append(
                CanonicalDevice(
                    canonical_hostname=display_label(primary),
                    aliases=_aliases(merged.hostnames, display_label(primary)),
                    management_ips=merged.management_ips,
                    vendor=None,
                    platform=None,
                    os_name=None,
                    os_version=None,
                    serial_number=merged.serial_number,
                    device_ids=(),
                    sources=(merged.source,),
                    discovered=False,
                )
            )
        return tuple(observed)


def _aliases(hostnames: tuple[str, ...], display: str) -> tuple[str, ...]:
    seen: list[str] = []
    for value in hostnames:
        cleaned = value.strip().rstrip(".")
        if cleaned and cleaned != display and cleaned not in seen:
            seen.append(cleaned)
    return tuple(sorted(seen))


def _display_tables(
    devices: tuple[CanonicalDevice, ...],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Map every observed hostname form to its cluster display name.

    If two distinct clusters would collapse to the same short display name,
    each keeps its full first alias instead so different devices never share
    a label (no false merges in the viewer).
    """

    display_counts: dict[str, int] = {}
    for device in devices:
        key = normalize_hostname(device.canonical_hostname)
        display_counts[key] = display_counts.get(key, 0) + 1

    display_by_key: dict[str, str] = {}
    aliases_by_display: dict[str, tuple[str, ...]] = {}
    for device in devices:
        display = device.canonical_hostname
        if display_counts[normalize_hostname(display)] > 1 and device.aliases:
            display = device.aliases[0]
        aliases = tuple(value for value in device.aliases if value != display)
        aliases_by_display[normalize_hostname(display)] = aliases
        display_by_key.setdefault(normalize_hostname(display), display)
        for value in (device.canonical_hostname, *device.aliases):
            display_by_key.setdefault(normalize_hostname(value), display)
    return display_by_key, aliases_by_display
