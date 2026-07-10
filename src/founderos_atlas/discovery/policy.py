"""Discovery boundary policy: which neighbors traversal may follow.

A discovery profile is an entry point, not a site boundary. Whether Atlas
follows a discovered neighbor is an explicit, structured policy decision —
never an accident of reachability. Every decision carries a verdict and a
human-readable reason, and neighbors that are not traversed are still
*recorded* as observed relationships: Atlas never pretends an out-of-scope
neighbor does not exist.

Verdicts:

- ``allowed``      — traversal may connect to the neighbor.
- ``denied``       — an explicit rule (deny list / excluded range) forbids it.
- ``observe-only`` — record the relationship but do not traverse (outside the
                     included ranges, protocol not followed, or no usable
                     management address).
- ``unknown``      — not enough evidence to classify; treated as observe-only
                     by traversal (uncertainty must never auto-traverse).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from ipaddress import ip_address, ip_network
from typing import Any


BOUNDARY_ALLOWED = "allowed"
BOUNDARY_DENIED = "denied"
BOUNDARY_OBSERVE_ONLY = "observe-only"
BOUNDARY_UNKNOWN = "unknown"

_VERDICTS = (
    BOUNDARY_ALLOWED,
    BOUNDARY_DENIED,
    BOUNDARY_OBSERVE_ONLY,
    BOUNDARY_UNKNOWN,
)

DEFAULT_PROTOCOLS = ("cdp",)
SUPPORTED_PROTOCOLS = ("cdp", "lldp")


@dataclass(frozen=True)
class BoundaryDecision:
    """One traversal decision with its reason — auditable, never implicit."""

    verdict: str
    reason: str

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICTS:
            raise ValueError(f"verdict must be one of {_VERDICTS}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")

    @property
    def traversable(self) -> bool:
        return self.verdict == BOUNDARY_ALLOWED


@dataclass(frozen=True)
class BoundaryPolicy:
    """Traversal boundaries for one discovery profile.

    Empty ``include_cidrs`` means "no range restriction". Hostname rules use
    case-insensitive glob patterns (``hyd-*``, ``*-fw01``). Deny always wins
    over allow; allow wins over range scoping; anything outside declared
    ranges is observe-only rather than silently followed.
    """

    include_cidrs: tuple[str, ...] = ()
    exclude_cidrs: tuple[str, ...] = ()
    allow_hostnames: tuple[str, ...] = ()
    deny_hostnames: tuple[str, ...] = ()
    allowed_protocols: tuple[str, ...] = DEFAULT_PROTOCOLS

    def __post_init__(self) -> None:
        for name in ("include_cidrs", "exclude_cidrs", "allow_hostnames", "deny_hostnames"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
        for name in ("include_cidrs", "exclude_cidrs"):
            for value in getattr(self, name):
                try:
                    ip_network(value, strict=False)
                except ValueError as error:
                    raise ValueError(f"{name} entry {value!r} is not a valid CIDR") from error
        protocols = tuple(str(item).casefold() for item in self.allowed_protocols)
        unknown = [item for item in protocols if item not in SUPPORTED_PROTOCOLS]
        if unknown:
            raise ValueError(
                f"allowed_protocols may contain {SUPPORTED_PROTOCOLS}; got {unknown}"
            )
        object.__setattr__(self, "allowed_protocols", protocols)

    def evaluate_neighbor(
        self,
        *,
        hostname: str | None,
        management_ip: str | None,
        protocol: str | None = None,
    ) -> BoundaryDecision:
        """Classify one observed neighbor. Uncertainty never auto-traverses."""

        name = (hostname or "").strip()
        lowered = name.casefold()
        for pattern in self.deny_hostnames:
            if lowered and fnmatchcase(lowered, pattern.casefold()):
                return BoundaryDecision(
                    BOUNDARY_DENIED, f"hostname matches deny rule {pattern!r}"
                )
        if protocol is not None and protocol.casefold() not in self.allowed_protocols:
            return BoundaryDecision(
                BOUNDARY_OBSERVE_ONLY,
                f"protocol {protocol!r} is not followed by this profile",
            )
        for pattern in self.allow_hostnames:
            if lowered and fnmatchcase(lowered, pattern.casefold()):
                return BoundaryDecision(
                    BOUNDARY_ALLOWED, f"hostname matches allow rule {pattern!r}"
                )
        if management_ip is None:
            return BoundaryDecision(
                BOUNDARY_OBSERVE_ONLY, "no management IP advertised"
            )
        try:
            address = ip_address(management_ip)
        except ValueError:
            return BoundaryDecision(
                BOUNDARY_UNKNOWN,
                f"management address {management_ip!r} could not be classified",
            )
        for cidr in self.exclude_cidrs:
            if address in ip_network(cidr, strict=False):
                return BoundaryDecision(
                    BOUNDARY_DENIED, f"management IP is inside excluded range {cidr}"
                )
        if self.include_cidrs:
            if not any(
                address in ip_network(cidr, strict=False)
                for cidr in self.include_cidrs
            ):
                return BoundaryDecision(
                    BOUNDARY_OBSERVE_ONLY,
                    "management IP is outside the profile's included ranges",
                )
        return BoundaryDecision(BOUNDARY_ALLOWED, "within discovery boundaries")

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_cidrs": list(self.include_cidrs),
            "exclude_cidrs": list(self.exclude_cidrs),
            "allow_hostnames": list(self.allow_hostnames),
            "deny_hostnames": list(self.deny_hostnames),
            "allowed_protocols": list(self.allowed_protocols),
        }

    @classmethod
    def from_dict(cls, value) -> "BoundaryPolicy":
        if not isinstance(value, dict):
            raise ValueError("boundary policy must be a mapping")

        def strings(key: str) -> tuple[str, ...]:
            items = value.get(key) or ()
            return tuple(str(item) for item in items)

        return cls(
            include_cidrs=strings("include_cidrs"),
            exclude_cidrs=strings("exclude_cidrs"),
            allow_hostnames=strings("allow_hostnames"),
            deny_hostnames=strings("deny_hostnames"),
            allowed_protocols=strings("allowed_protocols") or DEFAULT_PROTOCOLS,
        )
