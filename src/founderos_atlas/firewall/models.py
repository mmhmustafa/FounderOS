"""Canonical firewall models — vendor-independent, secret-free, JSON-plain.

Every firewall driver (FortiOS, PAN-OS, and any future firewall) parses
its own CLI/API into THESE records. Downstream code reads them and never
sees a vendor. The action vocabulary is normalized (a FortiGate "accept"
and a Palo Alto "allow" are both :data:`ACTION_ALLOW`) so Policy can
reason about a default-deny posture the same way on every platform.

Evidence, not intent, and never secrets: a policy's action, zones and
status are recorded; a VPN's endpoints and up/down state are recorded;
a pre-shared key, certificate or password is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# -- normalized security-policy actions --------------------------------------
# The one place vendor verbs collapse into a shared vocabulary. A driver
# maps its platform's word ("accept", "allow", "deny", "drop", "reset")
# onto one of these; downstream reasons only about these.
ACTION_ALLOW = "allow"
ACTION_DENY = "deny"            # blocks — silent drop or active reject
ACTION_UNKNOWN = "unknown"
ACTIONS = (ACTION_ALLOW, ACTION_DENY, ACTION_UNKNOWN)

# Virtual-firewall kinds. A FortiGate partitions into VDOMs; a Palo Alto
# into virtual systems (vsys). Both are "one physical box, many isolated
# firewalls" — the same canonical concept under two vendor names.
CONTEXT_VDOM = "vdom"
CONTEXT_VSYS = "vsys"

# NAT directions, normalized.
NAT_SOURCE = "source"
NAT_DESTINATION = "destination"
NAT_STATIC = "static"
NAT_UNKNOWN = "unknown"


def _tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    return tuple(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class FirewallZone:
    """A security zone and the interfaces bound to it.

    Zones are the firewall's segmentation primitive; a security policy is
    written between zones, not between raw interfaces. ``virtual_context``
    names the VDOM/vsys the zone lives in, or is None on a single-context
    device.
    """

    name: str
    interfaces: tuple[str, ...] = ()
    virtual_context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "interfaces": list(self.interfaces),
            "virtual_context": self.virtual_context,
        }


@dataclass(frozen=True)
class SecurityPolicy:
    """One ordered security rule, normalized across vendors.

    Only summary evidence is kept (Part: "collect evidence only, no full
    rule analysis"): the match tuple, the normalized action, whether it is
    enabled, and an observed hit count where the platform reports one. No
    deep-inspection profile, no rule body beyond what identifies it.
    """

    policy_id: str
    name: str | None = None
    from_zones: tuple[str, ...] = ()
    to_zones: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    destinations: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    applications: tuple[str, ...] = ()
    action: str = ACTION_UNKNOWN
    log: bool | None = None
    enabled: bool = True
    hit_count: int | None = None
    virtual_context: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_zones", _tuple(self.from_zones))
        object.__setattr__(self, "to_zones", _tuple(self.to_zones))
        object.__setattr__(self, "sources", _tuple(self.sources))
        object.__setattr__(self, "destinations", _tuple(self.destinations))
        object.__setattr__(self, "services", _tuple(self.services))
        object.__setattr__(self, "applications", _tuple(self.applications))
        if self.action not in ACTIONS:
            object.__setattr__(self, "action", ACTION_UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "from_zones": list(self.from_zones),
            "to_zones": list(self.to_zones),
            "sources": list(self.sources),
            "destinations": list(self.destinations),
            "services": list(self.services),
            "applications": list(self.applications),
            "action": self.action,
            "log": self.log,
            "enabled": self.enabled,
            "hit_count": self.hit_count,
            "virtual_context": self.virtual_context,
        }


@dataclass(frozen=True)
class NatRule:
    """A NAT rule summary. Directions are normalized; the translation is
    described by endpoint names, never expanded into a table."""

    rule_id: str
    name: str | None = None
    nat_type: str = NAT_UNKNOWN
    original_sources: tuple[str, ...] = ()
    original_destinations: tuple[str, ...] = ()
    translated_source: str | None = None
    translated_destination: str | None = None
    virtual_context: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_sources", _tuple(self.original_sources))
        object.__setattr__(
            self, "original_destinations", _tuple(self.original_destinations)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "nat_type": self.nat_type,
            "original_sources": list(self.original_sources),
            "original_destinations": list(self.original_destinations),
            "translated_source": self.translated_source,
            "translated_destination": self.translated_destination,
            "virtual_context": self.virtual_context,
        }


@dataclass(frozen=True)
class VpnTunnel:
    """A VPN tunnel's identity and observed state — never its key.

    ``status`` is the observed phase-2/tunnel state ("up"/"down"/"unknown").
    Pre-shared keys and certificates are deliberately absent: they are
    secrets, and this is evidence.
    """

    name: str
    tunnel_type: str = "unknown"     # ipsec | ssl | gre | unknown
    local_gateway: str | None = None
    remote_gateway: str | None = None
    status: str = "unknown"
    virtual_context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tunnel_type": self.tunnel_type,
            "local_gateway": self.local_gateway,
            "remote_gateway": self.remote_gateway,
            "status": self.status,
            "virtual_context": self.virtual_context,
        }


@dataclass(frozen=True)
class VirtualContext:
    """A virtual firewall inside one physical box (VDOM or vsys).

    This is what makes a firewall multi-tenant, and it has no router
    equivalent. Counts summarize what was collected per context so a
    consumer can show "3 virtual firewalls" without re-deriving it.
    """

    name: str
    context_type: str                 # vdom | vsys
    zone_count: int = 0
    policy_count: int = 0
    interface_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "context_type": self.context_type,
            "zone_count": self.zone_count,
            "policy_count": self.policy_count,
            "interface_count": self.interface_count,
        }


@dataclass(frozen=True)
class HaPeer:
    """High-availability peering evidence. A firewall's availability model
    (active/passive, active/active) and its peer, from the device's own
    HA status output."""

    role: str = "unknown"             # primary | secondary | active | passive
    mode: str | None = None           # a-p | a-a | standalone | unknown
    peer_name: str | None = None
    peer_serial: str | None = None
    status: str = "unknown"           # in-sync | out-of-sync | ...
    group: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "mode": self.mode,
            "peer_name": self.peer_name,
            "peer_serial": self.peer_serial,
            "status": self.status,
            "group": self.group,
        }


@dataclass(frozen=True)
class FirewallEvidence:
    """The canonical firewall picture — the one object drivers produce and
    downstream consumes. Kept entirely separate from routing evidence."""

    zones: tuple[FirewallZone, ...] = ()
    security_policies: tuple[SecurityPolicy, ...] = ()
    nat_rules: tuple[NatRule, ...] = ()
    vpns: tuple[VpnTunnel, ...] = ()
    virtual_contexts: tuple[VirtualContext, ...] = ()
    ha_peers: tuple[HaPeer, ...] = ()
    ha_mode: str | None = None
    source_commands: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (
            self.zones or self.security_policies or self.nat_rules
            or self.vpns or self.virtual_contexts or self.ha_peers
        )

    @property
    def default_action(self) -> str:
        """The action of the LAST enabled policy — the implicit posture a
        packet meets if nothing above matched. ``unknown`` when no policy
        evidence was collected; never guessed."""

        for policy in reversed(self.security_policies):
            if policy.enabled:
                return policy.action
        return ACTION_UNKNOWN

    def summary(self) -> dict[str, Any]:
        actions: dict[str, int] = {}
        for policy in self.security_policies:
            actions[policy.action] = actions.get(policy.action, 0) + 1
        return {
            "zone_count": len(self.zones),
            "policy_count": len(self.security_policies),
            "policies_by_action": dict(sorted(actions.items())),
            "nat_rule_count": len(self.nat_rules),
            "vpn_count": len(self.vpns),
            "vpns_up": sum(1 for tunnel in self.vpns if tunnel.status == "up"),
            "virtual_context_count": len(self.virtual_contexts),
            "ha_mode": self.ha_mode,
            "ha_peer_count": len(self.ha_peers),
            "default_action": self.default_action,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "zones": [zone.to_dict() for zone in self.zones],
            "security_policies": [
                policy.to_dict() for policy in self.security_policies
            ],
            "nat_rules": [rule.to_dict() for rule in self.nat_rules],
            "vpns": [tunnel.to_dict() for tunnel in self.vpns],
            "virtual_contexts": [
                context.to_dict() for context in self.virtual_contexts
            ],
            "ha_peers": [peer.to_dict() for peer in self.ha_peers],
            "ha_mode": self.ha_mode,
            "source_commands": list(self.source_commands),
            "summary": self.summary(),
        }
