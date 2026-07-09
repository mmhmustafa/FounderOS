"""Immutable saved discovery profile model.

A profile persists everything needed to re-run a discovery *except* the
password, which lives only in a secure credential store and is referenced
here by ``credential_ref``. No password field exists on this model by
design, so a profile can never serialize a secret.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
import re
from typing import Any

from .exceptions import InvalidProfileError


PROFILE_SCHEMA_VERSION = "1.0.0"
CREDENTIAL_REF_PREFIX = "atlas-profile"

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_LIMIT = 4096


def normalize_name(name: str) -> str:
    """Case-insensitive lookup key for a profile name."""

    return " ".join(str(name).strip().split()).casefold()


def profile_id_for(name: str) -> str:
    """Filesystem/credential-safe identifier derived from a profile name."""

    slug = _SLUG_PATTERN.sub("-", str(name).strip().casefold()).strip("-")
    return slug or "profile"


def credential_ref_for(profile_id: str) -> str:
    return f"{CREDENTIAL_REF_PREFIX}:{profile_id}"


@dataclass(frozen=True)
class DiscoveryProfile:
    """A reusable discovery target and its saved settings — never a password."""

    profile_id: str
    name: str
    management_ip: str
    username: str
    credential_ref: str
    site: str | None = None
    max_depth: int = 1
    max_devices: int = 10
    collect_configuration: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    last_discovery: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("profile_id", "name", "username", "credential_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidProfileError(f"{field_name} must be a non-empty string")
        try:
            object.__setattr__(self, "management_ip", str(ip_address(str(self.management_ip).strip())))
        except ValueError as error:
            raise InvalidProfileError(
                f"management IP is not a valid address: {self.management_ip!r}"
            ) from error
        for field_name in ("max_depth", "max_devices"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidProfileError(f"{field_name} must be an integer")
        if self.max_depth < 0 or self.max_depth > _MAX_LIMIT:
            raise InvalidProfileError("max_depth must be between 0 and 4096")
        if self.max_devices < 1 or self.max_devices > _MAX_LIMIT:
            raise InvalidProfileError("max_devices must be between 1 and 4096")
        if not isinstance(self.collect_configuration, bool):
            raise InvalidProfileError("collect_configuration must be a boolean")
        object.__setattr__(self, "name", " ".join(self.name.strip().split()))
        object.__setattr__(self, "site", (self.site.strip() or None) if isinstance(self.site, str) else None)

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "name": self.name,
            "site": self.site,
            "management_ip": self.management_ip,
            "username": self.username,
            "credential_ref": self.credential_ref,
            "max_depth": self.max_depth,
            "max_devices": self.max_devices,
            "collect_configuration": self.collect_configuration,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_discovery": self.last_discovery,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoveryProfile":
        if not isinstance(value, Mapping):
            raise InvalidProfileError("profile value must be a mapping")
        try:
            return cls(
                profile_id=value["profile_id"],
                name=value["name"],
                management_ip=value["management_ip"],
                username=value["username"],
                credential_ref=value["credential_ref"],
                site=value.get("site"),
                max_depth=value.get("max_depth", 1),
                max_devices=value.get("max_devices", 10),
                collect_configuration=bool(value.get("collect_configuration", False)),
                created_at=value.get("created_at"),
                updated_at=value.get("updated_at"),
                last_discovery=value.get("last_discovery"),
            )
        except KeyError as error:
            raise InvalidProfileError(f"profile is missing field {error}") from error
