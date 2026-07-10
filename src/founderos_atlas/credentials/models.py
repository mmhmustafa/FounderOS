"""Credential set, entry, and scope models. No field ever holds a secret.

A ``CredentialScope`` is a generic, vendor-neutral rule describing where a
credential applies: vendor, platform family, hostname globs, management
CIDRs, sites, profiles, or explicit device ids. Empty dimensions match
everything, so an entry with an empty scope is a general fallback. The
model is deliberately extensible for future kinds (SNMP communities,
NETCONF, REST APIs, cloud credentials) via the ``kind`` field.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from ipaddress import ip_address, ip_network
import re
from typing import Any


CREDENTIAL_SETS_SCHEMA_VERSION = "1.0.0"
KIND_SSH_PASSWORD = "ssh-password"

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str, fallback: str) -> str:
    slug = _SLUG.sub("-", str(value).strip().casefold()).strip("-")
    return slug or fallback


@dataclass(frozen=True)
class DeviceContext:
    """Everything safely known about a device before authenticating to it."""

    host: str
    hostname: str | None = None
    vendor: str | None = None
    platform: str | None = None
    site: str | None = None
    role: str | None = None
    profile_id: str | None = None
    device_id: str | None = None


@dataclass(frozen=True)
class CredentialScope:
    """Where a credential applies. Empty dimensions match everything."""

    vendors: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    hostname_patterns: tuple[str, ...] = ()
    cidrs: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    profile_ids: tuple[str, ...] = ()
    device_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "vendors", "platforms", "hostname_patterns", "cidrs",
            "sites", "roles", "profile_ids", "device_ids",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
        for value in self.cidrs:
            try:
                ip_network(value, strict=False)
            except ValueError as error:
                raise ValueError(f"cidrs entry {value!r} is not a valid CIDR") from error

    @property
    def is_unrestricted(self) -> bool:
        return not any(
            (
                self.vendors, self.platforms, self.hostname_patterns, self.cidrs,
                self.sites, self.roles, self.profile_ids, self.device_ids,
            )
        )

    def matches(self, context: DeviceContext) -> bool:
        """Whether this scope applies to the device.

        A restricted dimension only rejects when the context *knows* the
        attribute and it disagrees. Unknown attributes never satisfy a
        restriction (a vendor-scoped credential is not offered for a device
        whose vendor is unknown) — except CIDR scoping, which can always be
        evaluated from the management host.
        """

        if self.device_ids and not _known_in(context.device_id, self.device_ids):
            return False
        if self.profile_ids and not _known_in(context.profile_id, self.profile_ids):
            return False
        if self.vendors and not _known_in(context.vendor, self.vendors):
            return False
        if self.platforms and not _known_in(context.platform, self.platforms):
            return False
        if self.sites and not _known_in(context.site, self.sites):
            return False
        if self.roles and not _known_in(context.role, self.roles):
            return False
        if self.hostname_patterns:
            name = (context.hostname or "").strip().casefold()
            if not name or not any(
                fnmatchcase(name, pattern.casefold())
                for pattern in self.hostname_patterns
            ):
                return False
        if self.cidrs:
            try:
                address = ip_address(context.host)
            except ValueError:
                return False
            if not any(
                address in ip_network(cidr, strict=False) for cidr in self.cidrs
            ):
                return False
        return True

    def match_specificity(self, context: DeviceContext) -> int | None:
        """How specifically this scope matches the device; None = no match.

        Lower is more specific and is tried earlier (lockout protection:
        never spray a generic credential where a targeted one exists):

        - 0: explicit device id
        - 1: exact host address (/32 or /128) or exact hostname
        - 2: CIDR range or hostname pattern
        - 3: vendor / platform family
        - 4: site / role / profile scope
        - 6: unrestricted general fallback
        (5 is reserved for the profile-default credential.)
        """

        if not self.matches(context):
            return None
        if self.device_ids:
            return 0
        if self.cidrs:
            address = ip_address(context.host)
            matched = max(
                ip_network(cidr, strict=False).prefixlen
                for cidr in self.cidrs
                if address in ip_network(cidr, strict=False)
            )
            if matched == address.max_prefixlen:
                return 1
            return 2
        if self.hostname_patterns:
            name = (context.hostname or "").strip().casefold()
            exact = any(
                not any(char in pattern for char in "*?[")
                and name == pattern.strip().casefold()
                for pattern in self.hostname_patterns
            )
            return 1 if exact else 2
        if self.vendors or self.platforms:
            return 3
        if self.sites or self.roles or self.profile_ids:
            return 4
        return 6

    def summary(self) -> str:
        """One safe human-readable line for GUI/CLI listings."""

        parts: list[str] = []
        for label, values in (
            ("vendor", self.vendors),
            ("platform", self.platforms),
            ("hostname", self.hostname_patterns),
            ("range", self.cidrs),
            ("site", self.sites),
            ("role", self.roles),
            ("profile", self.profile_ids),
            ("device", self.device_ids),
        ):
            if values:
                parts.append(f"{label}: {', '.join(values)}")
        return "; ".join(parts) if parts else "any device permitted by policy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendors": list(self.vendors),
            "platforms": list(self.platforms),
            "hostname_patterns": list(self.hostname_patterns),
            "cidrs": list(self.cidrs),
            "sites": list(self.sites),
            "roles": list(self.roles),
            "profile_ids": list(self.profile_ids),
            "device_ids": list(self.device_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "CredentialScope":
        value = value or {}

        def strings(key: str) -> tuple[str, ...]:
            return tuple(str(item) for item in (value.get(key) or ()))

        return cls(
            vendors=strings("vendors"),
            platforms=strings("platforms"),
            hostname_patterns=strings("hostname_patterns"),
            cidrs=strings("cidrs"),
            sites=strings("sites"),
            roles=strings("roles"),
            profile_ids=strings("profile_ids"),
            device_ids=strings("device_ids"),
        )


def _known_in(value: str | None, allowed: tuple[str, ...]) -> bool:
    if not value:
        return False
    lowered = value.strip().casefold()
    return any(lowered == item.strip().casefold() for item in allowed)


@dataclass(frozen=True)
class CredentialEntry:
    """One credential a set may offer: reference + username + priority.

    Lower priority numbers are tried first. ``credential_ref`` points into
    the secure provider; the secret itself never appears here.
    """

    entry_id: str
    label: str
    username: str
    credential_ref: str
    priority: int = 100
    scope: CredentialScope = field(default_factory=CredentialScope)
    kind: str = KIND_SSH_PASSWORD
    enabled: bool = True
    last_success: str | None = None

    def __post_init__(self) -> None:
        for name in ("entry_id", "label", "username", "credential_ref", "kind"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ValueError("priority must be an integer")
        if not isinstance(self.scope, CredentialScope):
            raise ValueError("scope must be a CredentialScope")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "label": self.label,
            "username": self.username,
            "credential_ref": self.credential_ref,
            "priority": self.priority,
            "scope": self.scope.to_dict(),
            "kind": self.kind,
            "enabled": self.enabled,
            "last_success": self.last_success,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CredentialEntry":
        try:
            return cls(
                entry_id=value["entry_id"],
                label=value["label"],
                username=value["username"],
                credential_ref=value["credential_ref"],
                priority=int(value.get("priority", 100)),
                scope=CredentialScope.from_dict(value.get("scope")),
                kind=str(value.get("kind", KIND_SSH_PASSWORD)),
                enabled=bool(value.get("enabled", True)),
                last_success=value.get("last_success"),
            )
        except KeyError as error:
            raise ValueError(f"credential entry is missing field {error}") from error


@dataclass(frozen=True)
class CredentialSet:
    """A named, ordered collection of credential entries."""

    set_id: str
    name: str
    description: str | None = None
    entries: tuple[CredentialEntry, ...] = ()

    def __post_init__(self) -> None:
        for name in ("set_id", "name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.entries, tuple) or not all(
            isinstance(item, CredentialEntry) for item in self.entries
        ):
            raise ValueError("entries must be a tuple of CredentialEntry")
        seen: set[str] = set()
        for entry in self.entries:
            if entry.entry_id in seen:
                raise ValueError(f"duplicate entry_id {entry.entry_id!r}")
            seen.add(entry.entry_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "set_id": self.set_id,
            "name": self.name,
            "description": self.description,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CredentialSet":
        try:
            return cls(
                set_id=value["set_id"],
                name=value["name"],
                description=value.get("description"),
                entries=tuple(
                    CredentialEntry.from_dict(entry)
                    for entry in (value.get("entries") or ())
                ),
            )
        except KeyError as error:
            raise ValueError(f"credential set is missing field {error}") from error
