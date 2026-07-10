"""Site, evidence, assignment, and catalog models.

Core principles encoded here:

- one subnet is never assumed to be one site: a site may hold many
  unrelated subnets, and one supernet may be subnetted across many sites;
- network ranges are only one *corroborating* signal — they can raise the
  confidence of an assignment made by another signal but can never assign
  a site by themselves;
- Atlas says "unknown" or "ambiguous" rather than inventing a site.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_network
import re
from typing import Any


CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

ASSIGNMENT_ASSIGNED = "assigned"
ASSIGNMENT_UNKNOWN = "unknown"
ASSIGNMENT_AMBIGUOUS = "ambiguous"

SITE_CATALOG_SCHEMA_VERSION = "1.0.0"

_SLUG = re.compile(r"[^a-z0-9]+")


def site_id_for(name: str) -> str:
    slug = _SLUG.sub("-", str(name).strip().casefold()).strip("-")
    return slug or "site"


@dataclass(frozen=True)
class SiteEvidence:
    """One observed signal pointing at (or corroborating) a site."""

    signal: str       # e.g. explicit-assignment, hostname-convention, seed-origin, subnet
    site_id: str
    detail: str
    assigning: bool   # False = corroborating-only (e.g. subnet)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "site_id": self.site_id,
            "detail": self.detail,
            "assigning": self.assigning,
        }


@dataclass(frozen=True)
class SiteAssignment:
    """The site conclusion for one device, with confidence and evidence."""

    status: str                      # assigned | unknown | ambiguous
    site_id: str | None
    confidence: str | None           # high | medium | low; None when not assigned
    explicit: bool
    evidence: tuple[SiteEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in (ASSIGNMENT_ASSIGNED, ASSIGNMENT_UNKNOWN, ASSIGNMENT_AMBIGUOUS):
            raise ValueError("status must be assigned, unknown, or ambiguous")
        if self.status == ASSIGNMENT_ASSIGNED and not self.site_id:
            raise ValueError("an assigned status requires a site_id")
        if self.status != ASSIGNMENT_ASSIGNED and self.site_id is not None:
            raise ValueError("unknown/ambiguous assignments carry no site_id")

    @property
    def label(self) -> str:
        if self.status == ASSIGNMENT_ASSIGNED:
            return self.site_id or "unknown"
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "site_id": self.site_id,
            "confidence": self.confidence,
            "explicit": self.explicit,
            "evidence": [item.to_dict() for item in self.evidence],
        }


def unknown_assignment(evidence: tuple[SiteEvidence, ...] = ()) -> SiteAssignment:
    return SiteAssignment(
        status=ASSIGNMENT_UNKNOWN,
        site_id=None,
        confidence=None,
        explicit=False,
        evidence=evidence,
    )


@dataclass(frozen=True)
class Site:
    """One user-defined site with its (optional) inference hints.

    ``hostname_patterns`` are case-insensitive globs; ``cidrs`` are
    corroborating hints only; ``device_ids``/``hostnames`` are explicit
    assignments (highest confidence).
    """

    site_id: str
    name: str
    description: str | None = None
    hostname_patterns: tuple[str, ...] = ()
    cidrs: tuple[str, ...] = ()
    explicit_hostnames: tuple[str, ...] = ()
    explicit_device_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("site_id", "name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for value in self.cidrs:
            try:
                ip_network(value, strict=False)
            except ValueError as error:
                raise ValueError(f"cidrs entry {value!r} is not a valid CIDR") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "name": self.name,
            "description": self.description,
            "hostname_patterns": list(self.hostname_patterns),
            "cidrs": list(self.cidrs),
            "explicit_hostnames": list(self.explicit_hostnames),
            "explicit_device_ids": list(self.explicit_device_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Site":
        def strings(key: str) -> tuple[str, ...]:
            return tuple(str(item) for item in (value.get(key) or ()))

        try:
            return cls(
                site_id=value["site_id"],
                name=value["name"],
                description=value.get("description"),
                hostname_patterns=strings("hostname_patterns"),
                cidrs=strings("cidrs"),
                explicit_hostnames=strings("explicit_hostnames"),
                explicit_device_ids=strings("explicit_device_ids"),
            )
        except KeyError as error:
            raise ValueError(f"site is missing field {error}") from error


@dataclass(frozen=True)
class SiteCatalog:
    """All user-defined sites for the workspace."""

    sites: tuple[Site, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for site in self.sites:
            if site.site_id in seen:
                raise ValueError(f"duplicate site_id {site.site_id!r}")
            seen.add(site.site_id)

    def get(self, site_id: str) -> Site | None:
        for site in self.sites:
            if site.site_id == site_id:
                return site
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SITE_CATALOG_SCHEMA_VERSION,
            "sites": [site.to_dict() for site in self.sites],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SiteCatalog":
        entries = value.get("sites") if isinstance(value, Mapping) else None
        return cls(
            sites=tuple(Site.from_dict(entry) for entry in (entries or ()))
        )
