"""Enterprise device and topology models with per-observation provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from founderos_atlas.sites import SiteAssignment


@dataclass(frozen=True)
class DeviceObservation:
    """One profile's sighting of a device in one discovery run."""

    profile_id: str
    profile_name: str
    run_id: str | None
    observed_at: str | None
    hostname: str | None
    management_ip: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "run_id": self.run_id,
            "observed_at": self.observed_at,
            "hostname": self.hostname,
            "management_ip": self.management_ip,
        }


@dataclass(frozen=True)
class EnterpriseDevice:
    """One canonical enterprise device with evidence, site, and provenance."""

    enterprise_id: str
    hostname: str
    aliases: tuple[str, ...]
    management_ips: tuple[str, ...]
    vendor: str | None
    platform: str | None
    os_version: str | None
    serial_number: str | None
    site: SiteAssignment
    observations: tuple[DeviceObservation, ...]
    credential_ref: str | None = None  # reference only — never a secret

    @property
    def profile_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for observation in self.observations:
            if observation.profile_id not in seen:
                seen.append(observation.profile_id)
        return tuple(seen)

    @property
    def profile_names(self) -> tuple[str, ...]:
        seen: list[str] = []
        for observation in self.observations:
            if observation.profile_name not in seen:
                seen.append(observation.profile_name)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enterprise_id": self.enterprise_id,
            "hostname": self.hostname,
            "aliases": list(self.aliases),
            "management_ips": list(self.management_ips),
            "vendor": self.vendor,
            "platform": self.platform,
            "os_version": self.os_version,
            "serial_number": self.serial_number,
            "site": self.site.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "credential_ref": self.credential_ref,
        }


@dataclass(frozen=True)
class EnterpriseTopology:
    """The aggregated latest state of every contributing network."""

    devices: tuple[EnterpriseDevice, ...]
    relationships: tuple[dict, ...] = field(default_factory=tuple)
    networks: tuple[str, ...] = ()

    @property
    def device_count(self) -> int:
        return len(self.devices)

    def devices_for_site(self, site_label: str) -> tuple[EnterpriseDevice, ...]:
        return tuple(
            device for device in self.devices if device.site.label == site_label
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_count": self.device_count,
            "devices": [device.to_dict() for device in self.devices],
            "relationships": list(self.relationships),
            "networks": list(self.networks),
        }
