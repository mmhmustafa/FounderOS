"""Build the enterprise topology from every profile's latest scoped state.

Pure aggregation with evidence-based canonical identity:

- **Strong evidence merges**: equal serial numbers (or other strong
  identifiers) always describe one physical device, even across profiles
  and administrative domains.
- **Corroborated merges**: hostname AND management IP both matching merges
  only when the contributing profiles declare no conflicting
  administrative domain (``domain_hint``) — the same device legitimately
  seen from two entry points (e.g. a WAN router observed by two sites).
- **Never merged**: hostname alone, or IP alone. Real enterprises reuse
  hostnames and RFC1918 addresses across domains; inventing equality would
  corrupt the inventory.

Because the view aggregates each profile's *latest* snapshot rather than
comparing runs, a device absent from one profile's discovery can never be
shown as removed from another profile's network. Per-profile baselines and
change reports (PR-031A) are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _replace
import json
from pathlib import Path
from typing import Any

from founderos_atlas.history import HistoryRepository
from founderos_atlas.identity.canonical import choose_primary_hostname, normalize_hostname
from founderos_atlas.sites import SiteCatalog, SiteInferenceEngine
from founderos_atlas.workspace import profile_scope

from .models import DeviceObservation, EnterpriseDevice, EnterpriseTopology


_UNKNOWN = frozenset({"", "unknown", "none"})


@dataclass(frozen=True)
class ScopeContribution:
    """One profile's latest snapshot plus the run that produced it."""

    profile_id: str
    profile_name: str
    snapshot: dict
    run_id: str | None = None
    observed_at: str | None = None
    site_hint: str | None = None
    domain_hint: str | None = None


class _Cluster:
    """Mutable accumulation of observations that describe one device."""

    def __init__(self) -> None:
        self.hostnames: list[str] = []
        self.ips: list[str] = []
        self.serials: set[str] = set()
        self.device_ids: list[str] = []
        self.vendor: str | None = None
        self.platform: str | None = None
        self.os_version: str | None = None
        self.serial_display: str | None = None
        self.domains: set[str] = set()
        self.site_hints: list[str] = []
        self.observations: list[DeviceObservation] = []

    def absorb(self, device: dict, contribution: ScopeContribution) -> None:
        hostname = _clean(device.get("hostname"))
        ip = _clean(device.get("management_ip"))
        serial = _clean(device.get("serial_number"))
        if hostname and hostname not in self.hostnames:
            self.hostnames.append(str(device.get("hostname")))
        if ip and ip not in self.ips:
            self.ips.append(ip)
        if serial:
            self.serials.add(serial.casefold())
            self.serial_display = self.serial_display or serial
        device_id = _clean(device.get("device_id"))
        if device_id and device_id not in self.device_ids:
            self.device_ids.append(device_id)
        self.vendor = self.vendor or _clean(device.get("vendor"))
        self.platform = self.platform or _clean(device.get("platform"))
        self.os_version = self.os_version or _clean(device.get("os_version"))
        if contribution.domain_hint:
            self.domains.add(contribution.domain_hint.strip().casefold())
        if contribution.site_hint and contribution.site_hint not in self.site_hints:
            self.site_hints.append(contribution.site_hint)
        self.observations.append(
            DeviceObservation(
                profile_id=contribution.profile_id,
                profile_name=contribution.profile_name,
                run_id=contribution.run_id,
                observed_at=contribution.observed_at,
                hostname=str(device.get("hostname")) if hostname else None,
                management_ip=ip,
            )
        )

    def matches(self, device: dict, contribution: ScopeContribution) -> bool:
        serial = _clean(device.get("serial_number"))
        if serial and serial.casefold() in self.serials:
            return True  # strong evidence: same physical device
        hostname = _clean(device.get("hostname"))
        ip = _clean(device.get("management_ip"))
        if not hostname or not ip:
            return False
        hostname_match = any(
            normalize_hostname(hostname) == normalize_hostname(existing)
            for existing in self.hostnames
        )
        if not (hostname_match and ip in self.ips):
            return False
        # hostname+IP agreement is weak evidence: enterprises reuse both.
        # It merges only when the operator explicitly declared both
        # profiles in the same administrative domain.
        domain = (contribution.domain_hint or "").strip().casefold()
        return bool(domain) and domain in self.domains


def build_enterprise_topology(
    contributions: tuple[ScopeContribution, ...] | list[ScopeContribution],
    *,
    catalog: SiteCatalog | None = None,
    credential_memory=None,
) -> EnterpriseTopology:
    """Merge every contribution into one provenance-preserving topology."""

    engine = SiteInferenceEngine(catalog)
    clusters: list[_Cluster] = []
    relationships: list[dict[str, Any]] = []
    networks: list[str] = []
    for contribution in contributions:
        if contribution.profile_name not in networks:
            networks.append(contribution.profile_name)
        devices = contribution.snapshot.get("devices") or ()
        for device in devices:
            if not isinstance(device, dict):
                continue
            for cluster in clusters:
                if cluster.matches(device, contribution):
                    cluster.absorb(device, contribution)
                    break
            else:
                cluster = _Cluster()
                cluster.absorb(device, contribution)
                clusters.append(cluster)
        hostname_by_id = {
            str(device.get("device_id")): str(device.get("hostname"))
            for device in devices
            if isinstance(device, dict)
        }
        for edge in contribution.snapshot.get("edges") or ():
            if not isinstance(edge, dict):
                continue
            relationships.append(
                {
                    "network": contribution.profile_name,
                    "profile_id": contribution.profile_id,
                    "local": hostname_by_id.get(
                        str(edge.get("local_device_id")),
                        str(edge.get("local_device_id")),
                    ),
                    "remote": str(edge.get("remote_hostname")),
                    "protocol": str(edge.get("protocol") or "unknown"),
                }
            )

    devices = tuple(
        _finalize(index, cluster, engine, credential_memory)
        for index, cluster in enumerate(clusters)
    )
    # Distinct clusters must never share an enterprise id. Without strong
    # evidence, two devices may legitimately reuse hostname AND address
    # (separate administrative domains) — they stay separate objects, so
    # their ids are disambiguated deterministically, never merged.
    seen_ids: dict[str, int] = {}
    unique: list[EnterpriseDevice] = []
    for device in devices:
        count = seen_ids.get(device.enterprise_id, 0)
        seen_ids[device.enterprise_id] = count + 1
        if count:
            device = _replace(
                device, enterprise_id=f"{device.enterprise_id}:{count + 1}"
            )
        unique.append(device)
    ordered = tuple(
        sorted(unique, key=lambda item: (item.site.label, item.hostname.casefold()))
    )
    return EnterpriseTopology(
        devices=ordered,
        relationships=tuple(relationships),
        networks=tuple(networks),
    )


def gather_scope_contributions(
    base_output_dir: str | Path, profiles
) -> tuple[ScopeContribution, ...]:
    """Every profile's latest snapshot as an observation contribution.

    Shared by the enterprise view and the federation layer (PR-037A) so
    observation gathering has exactly one implementation.
    """

    contributions: list[ScopeContribution] = []
    for profile in profiles:
        scope = profile_scope(base_output_dir, profile.profile_id, profile.name)
        snapshot = _load_json(scope.snapshot_path)
        if snapshot is None:
            continue
        record = HistoryRepository(scope.history_root).latest()
        contributions.append(
            ScopeContribution(
                profile_id=profile.profile_id,
                profile_name=profile.name,
                snapshot=snapshot,
                run_id=record.record_id if record is not None else None,
                observed_at=record.completed_at if record is not None else None,
                site_hint=getattr(profile, "site_hint", None) or getattr(profile, "site", None),
                domain_hint=getattr(profile, "domain_hint", None),
            )
        )
    return tuple(contributions)


def build_enterprise_view(
    base_output_dir: str | Path,
    profiles,
    *,
    catalog: SiteCatalog | None = None,
    credential_memory=None,
) -> EnterpriseTopology:
    """The enterprise topology from every profile's scoped latest state."""

    return build_enterprise_topology(
        gather_scope_contributions(base_output_dir, profiles),
        catalog=catalog,
        credential_memory=credential_memory,
    )


def _finalize(
    index: int, cluster: _Cluster, engine: SiteInferenceEngine, credential_memory
) -> EnterpriseDevice:
    primary = choose_primary_hostname(cluster.hostnames) or (
        cluster.ips[0] if cluster.ips else f"device-{index}"
    )
    aliases = tuple(
        name for name in cluster.hostnames
        if normalize_hostname(name) != normalize_hostname(primary)
    )
    site = engine.assign(
        hostname=primary,
        management_ips=tuple(cluster.ips),
        device_ids=tuple(cluster.device_ids),
        profile_site_hints=tuple(cluster.site_hints),
    )
    credential_ref = None
    if credential_memory is not None:
        for ip in cluster.ips:
            entry = credential_memory.recall(ip)
            if entry and entry.get("credential_ref"):
                credential_ref = str(entry["credential_ref"])
                break
    enterprise_id = (
        f"ent:{cluster.serial_display.casefold()}"
        if cluster.serial_display
        else f"ent:{normalize_hostname(primary)}:{cluster.ips[0] if cluster.ips else index}"
    )
    return EnterpriseDevice(
        enterprise_id=enterprise_id,
        hostname=primary,
        aliases=aliases,
        management_ips=tuple(cluster.ips),
        vendor=cluster.vendor,
        platform=cluster.platform,
        os_version=cluster.os_version,
        serial_number=cluster.serial_display,
        site=site,
        observations=tuple(cluster.observations),
        credential_ref=credential_ref,
    )


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and cleaned.casefold() not in _UNKNOWN else None


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
