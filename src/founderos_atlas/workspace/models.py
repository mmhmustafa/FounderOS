"""Immutable saved discovery profile model.

A profile persists everything needed to re-run a discovery *except* the
password, which lives only in a secure credential store and is referenced
here by ``credential_ref``. No password field exists on this model by
design, so a profile can never serialize a secret.

Since PR-033 a profile is modeled as an **entry point and policy**, not a
site or ownership boundary: it may carry multiple seed devices, a boundary
policy, references to shared credential sets, and site/administrative-
domain hints. Every new field is optional with a compatible default, so
profiles saved by earlier versions load unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
import re
from typing import Any

from founderos_atlas.discovery.policy import BoundaryPolicy

from .exceptions import InvalidProfileError


PROFILE_SCHEMA_VERSION = "1.1.0"
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
    # PR-033 entry-point semantics; all optional and backward compatible.
    description: str | None = None
    seeds: tuple[str, ...] = ()  # additional seeds; management_ip is seed #1
    boundary: BoundaryPolicy | None = None
    credential_sets: tuple[str, ...] = ()
    site_hint: str | None = None
    domain_hint: str | None = None
    # PR-043.9: a Discovery Profile is an observation point. Archiving hides
    # it from active discovery and enterprise aggregation without deleting
    # it or the Network/Enterprise Knowledge it contributed to.
    archived: bool = False
    # PR-044 (MEMORY): configuration collection is policy driven —
    # always | scheduled | manual | discovery-only | disabled. None keeps
    # backward compatibility: the legacy ``collect_configuration`` boolean
    # decides (True -> always, False -> disabled).
    collection_policy: str | None = None
    collection_schedule_hours: int = 24

    def __post_init__(self) -> None:
        for field_name in ("profile_id", "name"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidProfileError(f"{field_name} must be a non-empty string")
        for field_name in ("username", "credential_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise InvalidProfileError(f"{field_name} must be a string")
        # The real rule is not "a profile has a username" — it is **a profile
        # must have a way in**. Its own credential is one way; a credential set
        # is another, and the resolver has always accepted sets alone
        # (`profile_default` is optional at every layer). Requiring both meant
        # an operator with a saved credential set was made to retype a username
        # and password the engine never needed.
        has_own_credential = bool(self.username.strip()) and bool(
            self.credential_ref.strip()
        )
        if not has_own_credential and not self.credential_sets:
            raise InvalidProfileError(
                "a profile needs a way to authenticate: a username and password, "
                "or at least one credential set"
            )
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
        if not isinstance(self.archived, bool):
            raise InvalidProfileError("archived must be a boolean")
        if self.collection_policy is not None:
            from founderos_atlas.config_memory.policy import COLLECTION_POLICIES

            policy = str(self.collection_policy).strip().casefold()
            if policy not in COLLECTION_POLICIES:
                raise InvalidProfileError(
                    "collection_policy must be one of: "
                    + ", ".join(COLLECTION_POLICIES)
                )
            object.__setattr__(self, "collection_policy", policy)
        if (
            not isinstance(self.collection_schedule_hours, int)
            or isinstance(self.collection_schedule_hours, bool)
            or self.collection_schedule_hours < 1
        ):
            raise InvalidProfileError(
                "collection_schedule_hours must be a positive integer"
            )
        object.__setattr__(self, "name", " ".join(self.name.strip().split()))
        object.__setattr__(self, "site", (self.site.strip() or None) if isinstance(self.site, str) else None)
        normalized_seeds: list[str] = []
        for seed in self.seeds:
            try:
                cleaned = str(ip_address(str(seed).strip()))
            except ValueError as error:
                raise InvalidProfileError(
                    f"seed is not a valid address: {seed!r}"
                ) from error
            if cleaned != self.management_ip and cleaned not in normalized_seeds:
                normalized_seeds.append(cleaned)
        object.__setattr__(self, "seeds", tuple(normalized_seeds))
        if self.boundary is not None and not isinstance(self.boundary, BoundaryPolicy):
            raise InvalidProfileError("boundary must be a BoundaryPolicy or None")
        if not isinstance(self.credential_sets, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.credential_sets
        ):
            raise InvalidProfileError("credential_sets must be a tuple of set ids")
        for field_name in ("description", "site_hint", "domain_hint"):
            value = getattr(self, field_name)
            if isinstance(value, str):
                object.__setattr__(self, field_name, value.strip() or None)
            elif value is not None:
                raise InvalidProfileError(f"{field_name} must be a string or None")

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    @property
    def all_seeds(self) -> tuple[str, ...]:
        """Every seed entry point; the legacy management IP is always first."""

        return (self.management_ip, *self.seeds)

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
            "description": self.description,
            "seeds": list(self.seeds),
            "boundary": self.boundary.to_dict() if self.boundary is not None else None,
            "credential_sets": list(self.credential_sets),
            "site_hint": self.site_hint,
            "domain_hint": self.domain_hint,
            "archived": self.archived,
            "collection_policy": self.collection_policy,
            "collection_schedule_hours": self.collection_schedule_hours,
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
                description=value.get("description"),
                seeds=tuple(str(item) for item in (value.get("seeds") or ())),
                boundary=(
                    BoundaryPolicy.from_dict(value["boundary"])
                    if value.get("boundary")
                    else None
                ),
                credential_sets=tuple(
                    str(item) for item in (value.get("credential_sets") or ())
                ),
                site_hint=value.get("site_hint"),
                domain_hint=value.get("domain_hint"),
                archived=bool(value.get("archived", False)),
                collection_policy=value.get("collection_policy"),
                collection_schedule_hours=int(
                    value.get("collection_schedule_hours", 24)
                ),
            )
        except KeyError as error:
            raise InvalidProfileError(f"profile is missing field {error}") from error
