"""Build the federated Enterprise Graph from profile observations.

Reuses the PR-033 canonical-identity engine (``build_enterprise_topology``:
serial numbers always merge; hostname+IP merges only within a declared
administrative domain; hostname alone or IP alone never merges) and layers
on top of it:

- **Canonical interfaces**: the union of every observation's interface
  table per canonical device, newest observation winning state conflicts
  deterministically, provenance retained per interface.
- **Canonical links**: each profile's edges resolved onto canonical
  devices. An edge's far end resolves ONLY within the observing profile's
  own snapshot — resolving a bare hostname across profiles would invent
  connectivity from name-only evidence. Cross-profile connectivity arises
  naturally when a merged device (proven by strong evidence) is an
  endpoint in more than one profile's edges.
- **Merge decisions**: the WHY for every canonical device — which
  evidence merged its observations (or why it stayed single) with a
  documented confidence.
- **Unknown boundaries**: neighbor-announced devices that were never
  discovered stay visible as boundary links, never invented as inventory.
"""

from __future__ import annotations

from founderos_atlas.enterprise import ScopeContribution, build_enterprise_topology
from founderos_atlas.identity.canonical import normalize_hostname
from founderos_atlas.sites import SiteCatalog

from .models import (
    CONFIDENCE_CORROBORATED_MERGE,
    CONFIDENCE_SERIAL_MERGE,
    CONFIDENCE_SINGLE_WEAK,
    CONFIDENCE_SINGLE_WITH_SERIAL,
    CanonicalInterface,
    CanonicalLink,
    ContributionSummary,
    EnterpriseGraph,
    LinkObservation,
    MergeDecision,
)


def build_enterprise_graph(
    contributions: tuple[ScopeContribution, ...] | list[ScopeContribution],
    *,
    catalog: SiteCatalog | None = None,
    credential_memory=None,
) -> EnterpriseGraph:
    """One provenance-preserving graph from every profile's observations."""

    contributions = tuple(contributions)
    topology = build_enterprise_topology(
        contributions, catalog=catalog, credential_memory=credential_memory
    )

    # Resolver: (profile_id, observed hostname) -> canonical device.
    # An observation's hostname resolves only within its own profile —
    # global hostname matching would be name-only merging by the back door.
    by_profile_hostname: dict[tuple[str, str], str] = {}
    device_by_id = {device.enterprise_id: device for device in topology.devices}
    for device in topology.devices:
        for observation in device.observations:
            if observation.hostname:
                key = (
                    observation.profile_id,
                    normalize_hostname(observation.hostname),
                )
                by_profile_hostname.setdefault(key, device.enterprise_id)

    interfaces = _merge_interfaces(contributions, by_profile_hostname)
    links, unknowns = _build_links(
        contributions, by_profile_hostname, device_by_id
    )
    decisions = tuple(
        _decide(device) for device in topology.devices
    )
    summaries = tuple(
        ContributionSummary(
            profile_id=contribution.profile_id,
            profile_name=contribution.profile_name,
            run_id=contribution.run_id,
            observed_at=contribution.observed_at,
            device_count=len(contribution.snapshot.get("devices") or ()),
            edge_count=len(contribution.snapshot.get("edges") or ()),
        )
        for contribution in contributions
    )
    return EnterpriseGraph(
        devices=topology.devices,
        interfaces=interfaces,
        links=links,
        merge_decisions=decisions,
        contributions=summaries,
        unknowns=unknowns,
        attributes={"networks": list(topology.networks)},
    )


# -- merge decisions --------------------------------------------------------------


def _decide(device) -> MergeDecision:
    """The explainable WHY behind one canonical device's identity."""

    profiles = device.profile_names
    count = len(device.observations)
    merged = count > 1
    if merged:
        if device.serial_number:
            reason = (
                "Merged: every observation reports the same serial number — "
                "strong evidence of one physical device."
            )
            evidence = (
                f"serial number {device.serial_number} observed by "
                + ", ".join(profiles),
            )
            confidence = CONFIDENCE_SERIAL_MERGE
        else:
            reason = (
                "Merged: hostname and management address agree, and the "
                "contributing profiles declare the same administrative "
                "domain. Weak evidence alone never merges."
            )
            evidence = (
                f"hostname {device.hostname} and management address(es) "
                f"{', '.join(device.management_ips)} corroborated across "
                + ", ".join(profiles),
            )
            confidence = CONFIDENCE_CORROBORATED_MERGE
    else:
        if device.serial_number:
            reason = (
                "Single observation with a strong identifier; no other "
                "observation presented matching evidence."
            )
            evidence = (f"serial number {device.serial_number}",)
            confidence = CONFIDENCE_SINGLE_WITH_SERIAL
        else:
            reason = (
                "Single observation without a strong identifier. If this "
                "device is also observed elsewhere, Atlas keeps the "
                "observations separate until deterministic evidence proves "
                "they are the same object."
            )
            evidence = ("no serial number collected",)
            confidence = CONFIDENCE_SINGLE_WEAK
    return MergeDecision(
        enterprise_id=device.enterprise_id,
        hostname=device.hostname,
        merged=merged,
        observation_count=count,
        profiles=profiles,
        reason=reason,
        evidence=evidence,
        confidence=confidence,
    )


# -- canonical interfaces ----------------------------------------------------------


def _merge_interfaces(
    contributions: tuple[ScopeContribution, ...],
    resolver: dict[tuple[str, str], str],
) -> dict[str, tuple[CanonicalInterface, ...]]:
    """Union of interface tables per canonical device, provenance retained.

    When two observations disagree about an interface's state, the newest
    observation wins deterministically (ties broken by profile id); every
    contributing profile stays listed in ``observed_by``.
    """

    ordered = sorted(
        contributions,
        key=lambda item: (item.observed_at or "", item.profile_id),
        reverse=True,
    )
    merged: dict[str, dict[str, dict]] = {}
    for contribution in ordered:
        for device in contribution.snapshot.get("devices") or ():
            if not isinstance(device, dict) or not device.get("hostname"):
                continue
            enterprise_id = resolver.get(
                (
                    contribution.profile_id,
                    normalize_hostname(str(device.get("hostname"))),
                )
            )
            if enterprise_id is None:
                continue
            bucket = merged.setdefault(enterprise_id, {})
            for interface in device.get("interfaces") or ():
                if not isinstance(interface, dict) or not interface.get("name"):
                    continue
                name = str(interface.get("name"))
                entry = bucket.get(name.casefold())
                if entry is None:
                    bucket[name.casefold()] = {
                        "name": name,
                        "status": interface.get("status"),
                        "protocol_status": interface.get("protocol_status"),
                        "ip_address": interface.get("ip_address"),
                        "description": interface.get("description"),
                        "observed_by": [contribution.profile_name],
                    }
                elif contribution.profile_name not in entry["observed_by"]:
                    entry["observed_by"].append(contribution.profile_name)
    return {
        enterprise_id: tuple(
            CanonicalInterface(
                name=entry["name"],
                status=entry["status"],
                protocol_status=entry["protocol_status"],
                ip_address=entry["ip_address"],
                description=entry["description"],
                observed_by=tuple(sorted(entry["observed_by"])),
            )
            for _, entry in sorted(bucket.items())
        )
        for enterprise_id, bucket in merged.items()
    }


# -- canonical links ---------------------------------------------------------------


def _build_links(
    contributions: tuple[ScopeContribution, ...],
    resolver: dict[tuple[str, str], str],
    device_by_id: dict,
) -> tuple[tuple[CanonicalLink, ...], tuple[str, ...]]:
    collected: dict[tuple, dict] = {}
    unknowns: list[str] = []
    for contribution in contributions:
        hostname_by_device_id = {
            str(device.get("device_id")): str(device.get("hostname"))
            for device in contribution.snapshot.get("devices") or ()
            if isinstance(device, dict)
        }
        for edge in contribution.snapshot.get("edges") or ():
            if not isinstance(edge, dict):
                continue
            local_hostname = hostname_by_device_id.get(
                str(edge.get("local_device_id")), str(edge.get("local_device_id"))
            )
            remote_hostname = str(edge.get("remote_hostname") or "").strip()
            if not local_hostname or not remote_hostname:
                continue
            local_id = resolver.get(
                (contribution.profile_id, normalize_hostname(local_hostname))
            )
            if local_id is None:
                continue
            remote_id = resolver.get(
                (contribution.profile_id, normalize_hostname(remote_hostname))
            )
            if remote_id is None:
                unknowns.append(
                    f"{remote_hostname} is announced as a neighbor of "
                    f"{local_hostname} (observed by "
                    f"{contribution.profile_name}) but was never discovered "
                    "directly — an unknown boundary, not inventory."
                )
            local_interface = str(edge.get("local_interface") or "") or None
            remote_interface = str(edge.get("remote_interface") or "") or None
            key = _link_key(
                local_id,
                local_interface,
                remote_id or f"boundary:{normalize_hostname(remote_hostname)}",
                remote_interface,
            )
            observation = LinkObservation(
                profile_id=contribution.profile_id,
                profile_name=contribution.profile_name,
                run_id=contribution.run_id,
                observed_at=contribution.observed_at,
                protocol=str(edge.get("protocol") or "unknown"),
            )
            entry = collected.get(key)
            if entry is None:
                local_device = device_by_id[local_id]
                remote_device = device_by_id.get(remote_id) if remote_id else None
                collected[key] = {
                    "local_enterprise_id": local_id,
                    "local_hostname": local_device.hostname,
                    "local_interface": local_interface,
                    "remote_enterprise_id": remote_id,
                    "remote_hostname": (
                        remote_device.hostname if remote_device else remote_hostname
                    ),
                    "remote_interface": remote_interface,
                    "protocol": observation.protocol,
                    "observations": [observation],
                }
            elif not any(
                existing.profile_id == observation.profile_id
                and existing.run_id == observation.run_id
                for existing in entry["observations"]
            ):
                entry["observations"].append(observation)

    links: list[CanonicalLink] = []
    for _, entry in sorted(collected.items()):
        observing_profiles = {
            observation.profile_id for observation in entry["observations"]
        }
        endpoint_profiles = _endpoint_profiles(entry, device_by_id)
        links.append(
            CanonicalLink(
                local_enterprise_id=entry["local_enterprise_id"],
                local_hostname=entry["local_hostname"],
                local_interface=entry["local_interface"],
                remote_enterprise_id=entry["remote_enterprise_id"],
                remote_hostname=entry["remote_hostname"],
                remote_interface=entry["remote_interface"],
                protocol=entry["protocol"],
                observations=tuple(
                    sorted(
                        entry["observations"],
                        key=lambda item: (item.profile_id, item.run_id or ""),
                    )
                ),
                # A link joins the enterprise across observation points when
                # its endpoints' evidence comes from more than one profile.
                cross_profile=len(observing_profiles) > 1
                or len(endpoint_profiles) > 1,
            )
        )
    seen: set[str] = set()
    deduped_unknowns = tuple(
        item for item in unknowns if not (item in seen or seen.add(item))
    )
    return tuple(links), deduped_unknowns


def _endpoint_profiles(entry: dict, device_by_id: dict) -> set[str]:
    profiles: set[str] = set()
    for key in ("local_enterprise_id", "remote_enterprise_id"):
        device = device_by_id.get(entry.get(key))
        if device is not None:
            profiles.update(device.profile_ids)
    return profiles


def _link_key(
    local_id: str,
    local_interface: str | None,
    remote_id: str,
    remote_interface: str | None,
) -> tuple:
    """Direction-independent identity of one canonical link."""

    ends = sorted(
        (
            (local_id, (local_interface or "").casefold()),
            (remote_id, (remote_interface or "").casefold()),
        )
    )
    return (*ends[0], *ends[1])
