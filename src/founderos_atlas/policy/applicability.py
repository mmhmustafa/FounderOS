"""Deterministic policy targeting and applicability explanations.

Policy applicability is data, not Python predicates.  A selector can target
platforms, device roles, sites and site types, profile/network boundaries,
environments, tags, or explicitly named devices.  Dimensions are ANDed while
values within one dimension are ORed.  Explicit exclusions always win.

The evaluator returns an explanation for both outcomes.  Unknown attributes
do not get guessed: a policy that targets a role is not applicable when Atlas
has no role evidence for the device.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any


INTENT_REQUIRED = "required"
INTENT_RECOMMENDED = "recommended"
INTENT_INFORMATIONAL = "informational"
POLICY_INTENTS = (
    INTENT_REQUIRED,
    INTENT_RECOMMENDED,
    INTENT_INFORMATIONAL,
)


def _values(value) -> tuple[str, ...]:
    return tuple(
        str(item).strip()
        for item in (value or ())
        if str(item).strip()
    )


def _folded(values) -> frozenset[str]:
    return frozenset(str(value).strip().casefold() for value in values if value)


def _matches(value: str, patterns: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return any(fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


@dataclass(frozen=True)
class PolicyContext:
    """Canonical attributes known for one evaluated device."""

    device_id: str
    hostname: str
    platform: str = ""
    role: str = ""
    site: str = ""
    site_type: str = ""
    tags: tuple[str, ...] = ()
    profile: str = ""
    network: str = ""
    environment: str = ""

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        device_id: str = "",
        hostname: str = "",
        network: str = "",
    ) -> "PolicyContext":
        source = value or {}
        return cls(
            device_id=str(source.get("device_id") or device_id),
            hostname=str(source.get("hostname") or hostname),
            platform=str(source.get("platform") or ""),
            role=str(source.get("role") or ""),
            site=str(source.get("site") or ""),
            site_type=str(source.get("site_type") or ""),
            tags=_values(source.get("tags")),
            profile=str(source.get("profile") or ""),
            network=str(source.get("network") or network),
            environment=str(source.get("environment") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "platform": self.platform,
            "role": self.role,
            "site": self.site,
            "site_type": self.site_type,
            "tags": list(self.tags),
            "profile": self.profile,
            "network": self.network,
            "environment": self.environment,
        }


@dataclass(frozen=True)
class ApplicabilityDecision:
    applicable: bool
    explanation: str
    matched_dimensions: tuple[str, ...] = ()
    unmatched_dimensions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable": self.applicable,
            "explanation": self.explanation,
            "matched_dimensions": list(self.matched_dimensions),
            "unmatched_dimensions": list(self.unmatched_dimensions),
        }


@dataclass(frozen=True)
class PolicyApplicability:
    """Declarative selector for a policy.

    Empty selectors mean universal applicability, preserving historical policy
    definitions and evaluations.  Wildcards use shell-style matching and are
    case-insensitive.
    """

    platforms: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    site_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    networks: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    include_devices: tuple[str, ...] = ()
    exclude_devices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "platforms", "roles", "sites", "site_types", "tags", "profiles",
            "networks", "environments", "include_devices", "exclude_devices",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ValueError(f"{name} must be a tuple")
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} entries must be non-empty strings")

    @property
    def universal(self) -> bool:
        return not any(self.to_dict().values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "platforms": list(self.platforms),
            "roles": list(self.roles),
            "sites": list(self.sites),
            "site_types": list(self.site_types),
            "tags": list(self.tags),
            "profiles": list(self.profiles),
            "networks": list(self.networks),
            "environments": list(self.environments),
            "include_devices": list(self.include_devices),
            "exclude_devices": list(self.exclude_devices),
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any] | None
    ) -> "PolicyApplicability":
        source = value or {}
        return cls(
            platforms=_values(source.get("platforms")),
            roles=_values(source.get("roles")),
            sites=_values(source.get("sites")),
            site_types=_values(source.get("site_types")),
            tags=_values(source.get("tags")),
            profiles=_values(source.get("profiles")),
            networks=_values(source.get("networks")),
            environments=_values(source.get("environments")),
            include_devices=_values(source.get("include_devices")),
            exclude_devices=_values(source.get("exclude_devices")),
        )

    def decide(self, context: PolicyContext) -> ApplicabilityDecision:
        identities = tuple(
            value for value in (context.device_id, context.hostname) if value
        )
        if self.exclude_devices and any(
            _matches(identity, self.exclude_devices) for identity in identities
        ):
            return ApplicabilityDecision(
                False,
                "Not applicable: this device is explicitly excluded.",
                unmatched_dimensions=("device exclusion",),
            )

        checks: list[tuple[str, bool, str]] = []
        if self.include_devices:
            checks.append((
                "named device",
                any(_matches(identity, self.include_devices) for identity in identities),
                context.hostname or context.device_id or "unknown device",
            ))
        for label, value, patterns in (
            ("platform", context.platform, self.platforms),
            ("role", context.role, self.roles),
            ("site", context.site, self.sites),
            ("site type", context.site_type, self.site_types),
            ("profile", context.profile, self.profiles),
            ("network", context.network, self.networks),
            ("environment", context.environment, self.environments),
        ):
            if patterns:
                checks.append((label, bool(value) and _matches(value, patterns), value or "unknown"))
        if self.tags:
            wanted = _folded(self.tags)
            actual = _folded(context.tags)
            checks.append((
                "tag",
                bool(wanted & actual),
                ", ".join(context.tags) if context.tags else "none",
            ))

        if not checks:
            return ApplicabilityDecision(
                True,
                "Applicable to every device; no targeting selector is configured.",
            )

        matched = tuple(label for label, ok, _value in checks if ok)
        missed = tuple(label for label, ok, _value in checks if not ok)
        if missed:
            detail = "; ".join(
                f"{label} is {value}"
                for label, ok, value in checks
                if not ok
            )
            return ApplicabilityDecision(
                False,
                f"Not applicable: {detail}; the policy targets different values.",
                matched_dimensions=matched,
                unmatched_dimensions=missed,
            )
        return ApplicabilityDecision(
            True,
            "Applicable because the device matches "
            + ", ".join(matched)
            + ".",
            matched_dimensions=matched,
        )

