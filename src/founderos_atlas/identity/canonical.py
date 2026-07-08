"""Canonical device identity models for Atlas.

A physical device may be referenced by many identifiers across discovery
sources — bare hostname from ``show version``, FQDN from CDP, management
and loopback addresses, serial numbers, chassis IDs. ``DeviceIdentity``
carries every identifier observed for one observation; ``CanonicalDevice``
is the single merged identity a cluster of observations resolves to.
Original values are never destroyed: they become aliases and history.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from founderos_atlas.discovery.models import NetworkDevice, NetworkNeighbor


# Metadata keys recognized as device identifiers by default; vendors may
# populate any of these and future keys can be matched via custom rules.
RECOGNIZED_IDENTIFIER_KEYS = (
    "chassis_id",
    "system_mac",
    "uuid",
)

_UNKNOWN_VALUES = frozenset({"", "unknown"})


def normalize_hostname(value: str) -> str:
    """Lowercase, trim, and strip trailing dots; never destroys the original."""

    if not isinstance(value, str):
        return ""
    return value.strip().rstrip(".").casefold()


def short_hostname(value: str) -> str:
    """First DNS label of the normalized hostname (``r1.atlas.local`` -> ``r1``)."""

    return normalize_hostname(value).split(".", 1)[0]


def is_bare_hostname(value: str) -> bool:
    normalized = normalize_hostname(value)
    return bool(normalized) and "." not in normalized


def display_label(value: str) -> str:
    """First label of the original value with its casing preserved."""

    return value.strip().rstrip(".").split(".", 1)[0]


@dataclass(frozen=True)
class DeviceIdentity:
    """Every identifier observed for one device observation or reference."""

    hostnames: tuple[str, ...] = ()
    management_ips: tuple[str, ...] = ()
    serial_number: str | None = None
    extra_identifiers: Mapping[str, str] = field(default_factory=dict)
    source: str = "observation"

    @classmethod
    def from_device(cls, device: NetworkDevice) -> "DeviceIdentity":
        if not isinstance(device, NetworkDevice):
            raise TypeError("device must be a NetworkDevice")
        serial = device.serial_number
        if serial is not None and serial.casefold() in _UNKNOWN_VALUES:
            serial = None
        extra = {
            key: str(device.metadata[key])
            for key in RECOGNIZED_IDENTIFIER_KEYS
            if device.metadata.get(key)
        }
        hostnames = (device.hostname,) if _known(device.hostname) else ()
        return cls(
            hostnames=hostnames,
            management_ips=(device.management_ip,),
            serial_number=serial,
            extra_identifiers=extra,
            source=f"discovered:{device.device_id}",
        )

    @classmethod
    def from_neighbor(cls, neighbor: NetworkNeighbor) -> "DeviceIdentity":
        if not isinstance(neighbor, NetworkNeighbor):
            raise TypeError("neighbor must be a NetworkNeighbor")
        ips = (
            (neighbor.remote_management_ip,)
            if neighbor.remote_management_ip is not None
            else ()
        )
        return cls(
            hostnames=(neighbor.remote_hostname,),
            management_ips=ips,
            source=f"neighbor-of:{neighbor.local_device_id}",
        )

    def merged_with(self, other: "DeviceIdentity") -> "DeviceIdentity":
        extra = dict(self.extra_identifiers)
        extra.update(other.extra_identifiers)
        return DeviceIdentity(
            hostnames=_unique(self.hostnames + other.hostnames),
            management_ips=_unique(self.management_ips + other.management_ips),
            serial_number=self.serial_number or other.serial_number,
            extra_identifiers=extra,
            source=self.source,
        )


@dataclass(frozen=True)
class CanonicalDevice:
    """One physical device: a single canonical name plus everything observed."""

    canonical_hostname: str
    aliases: tuple[str, ...]
    management_ips: tuple[str, ...]
    vendor: str | None
    platform: str | None
    os_name: str | None
    os_version: str | None
    serial_number: str | None
    device_ids: tuple[str, ...]
    sources: tuple[str, ...]
    discovered: bool


def choose_primary_hostname(hostnames: Sequence[str]) -> str | None:
    """Pick the best original hostname value from a cluster, deterministically.

    Bare names beat FQDNs, fewer labels beat more, shorter beats longer,
    then normalized and original string order break remaining ties.
    """

    candidates = [value for value in hostnames if _known(value)]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda value: (
            0 if is_bare_hostname(value) else 1,
            normalize_hostname(value).count("."),
            len(normalize_hostname(value)),
            normalize_hostname(value),
            value,
        ),
    )


def _known(value: str | None) -> bool:
    return isinstance(value, str) and normalize_hostname(value) not in _UNKNOWN_VALUES


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)
