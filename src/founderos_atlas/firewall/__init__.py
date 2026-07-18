"""Vendor-neutral firewall evidence (PR-056, POLYGLOT Wave 2).

Firewalls are not routers. A firewall owns addressed interfaces and a
routing table like any layer-3 device — those normalize into the SAME
canonical ``NetworkDevice`` / ``NetworkInterface`` / ``NetworkNeighbor``
every platform uses — but its defining evidence is a security posture no
router reports: security zones, an ordered security-policy set, NAT, VPN
tunnels, virtual firewalls (FortiGate VDOMs, Palo Alto vsys), and HA
peering.

This package is to firewalls what ``routing`` is to OSPF/BGP: one set of
canonical, provenance-bearing, JSON-plain records that every firewall
driver populates and every downstream consumer reads WITHOUT ever
learning which vendor produced them. A driver stamps
``FirewallEvidence`` into ``device.metadata["firewall_evidence"]``;
Policy, Topology, Advisor and the Evidence Explorer read normalized
fields, never ``if vendor == "fortinet"``.

Nothing here holds a secret. VPN pre-shared keys, certificates and
passwords are never collected or represented — a tunnel's identity and
state are evidence; its key is not.
"""

from .models import (
    FirewallEvidence,
    FirewallZone,
    HaPeer,
    NatRule,
    SecurityPolicy,
    VirtualContext,
    VpnTunnel,
    ACTION_ALLOW,
    ACTION_DENY,
    ACTION_UNKNOWN,
    ACTIONS,
    CONTEXT_VDOM,
    CONTEXT_VSYS,
    NAT_DESTINATION,
    NAT_SOURCE,
    NAT_STATIC,
    NAT_UNKNOWN,
)

__all__ = [
    "FirewallEvidence",
    "FirewallZone",
    "HaPeer",
    "NatRule",
    "SecurityPolicy",
    "VirtualContext",
    "VpnTunnel",
    "ACTION_ALLOW",
    "ACTION_DENY",
    "ACTION_UNKNOWN",
    "ACTIONS",
    "NAT_STATIC",
    "NAT_UNKNOWN",
    "CONTEXT_VDOM",
    "CONTEXT_VSYS",
    "NAT_DESTINATION",
    "NAT_SOURCE",
]
