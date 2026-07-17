"""Configuration fingerprint (PR-045R, Part 6).

A *lightweight* structural summary of a configuration — counts, not meaning.

This is deliberately NOT semantic parsing. It answers one question cheaply:
does this configuration look structurally like the one before it? Exact change
detection already comes for free from content addressing (same bytes → same
hash); the fingerprint adds a fast, human-readable shape (how many interfaces,
BGP neighbours, VRFs…) that a future module can compare — "likely changed" vs
"likely unchanged" — without reading, decompressing, or parsing the whole
config.

It is kept independent of ``config_intelligence``'s richer extractor on
purpose: Enterprise Memory must not depend on the interpretation layer. These
are simple, deterministic line-shape counts, and they never carry a secret.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import content_sha256


_HOSTNAME = re.compile(r"^\s*hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
# An interface stanza opener on IOS/IOS-XE ("interface Gi0/1") or FRR
# ("interface eth1"). Loopbacks counted separately.
_INTERFACE = re.compile(r"^\s*interface\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_LOOPBACK = re.compile(r"^\s*interface\s+lo\S*", re.IGNORECASE | re.MULTILINE)
_BGP_NEIGHBOR = re.compile(r"^\s*neighbor\s+\S+\s+remote-as\b", re.IGNORECASE | re.MULTILINE)
_OSPF_NETWORK = re.compile(r"^\s*network\s+\S+\s+area\b", re.IGNORECASE | re.MULTILINE)
_ROUTER_OSPF = re.compile(r"^\s*router\s+ospf\b", re.IGNORECASE | re.MULTILINE)
_ROUTER_BGP = re.compile(r"^\s*router\s+bgp\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_ACL = re.compile(
    r"^\s*(?:ip\s+)?access-list\b|^\s*access-list\s+\d+", re.IGNORECASE | re.MULTILINE
)
_VRF = re.compile(
    r"^\s*(?:vrf\s+definition|ip\s+vrf)\s+\S+", re.IGNORECASE | re.MULTILINE
)
_VLAN = re.compile(r"^\s*vlan\s+\d+", re.IGNORECASE | re.MULTILINE)
_STATIC_ROUTE = re.compile(
    r"^\s*ip\s+route\b|^\s*ipv6\s+route\b", re.IGNORECASE | re.MULTILINE
)


@dataclass(frozen=True)
class ConfigurationFingerprint:
    """A cheap structural shape of a configuration. No secrets, no parsing."""

    config_sha256: str
    hostname: str | None
    line_count: int
    interface_count: int
    loopback_count: int
    bgp_neighbor_count: int
    bgp_as: str | None
    ospf_process_count: int
    ospf_network_count: int
    acl_count: int
    vrf_count: int
    vlan_count: int
    static_route_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_sha256": self.config_sha256,
            "hostname": self.hostname,
            "line_count": self.line_count,
            "interface_count": self.interface_count,
            "loopback_count": self.loopback_count,
            "bgp_neighbor_count": self.bgp_neighbor_count,
            "bgp_as": self.bgp_as,
            "ospf_process_count": self.ospf_process_count,
            "ospf_network_count": self.ospf_network_count,
            "acl_count": self.acl_count,
            "vrf_count": self.vrf_count,
            "vlan_count": self.vlan_count,
            "static_route_count": self.static_route_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ConfigurationFingerprint | None":
        if not value:
            return None
        return cls(
            config_sha256=str(value.get("config_sha256") or ""),
            hostname=value.get("hostname"),
            line_count=int(value.get("line_count") or 0),
            interface_count=int(value.get("interface_count") or 0),
            loopback_count=int(value.get("loopback_count") or 0),
            bgp_neighbor_count=int(value.get("bgp_neighbor_count") or 0),
            bgp_as=value.get("bgp_as"),
            ospf_process_count=int(value.get("ospf_process_count") or 0),
            ospf_network_count=int(value.get("ospf_network_count") or 0),
            acl_count=int(value.get("acl_count") or 0),
            vrf_count=int(value.get("vrf_count") or 0),
            vlan_count=int(value.get("vlan_count") or 0),
            static_route_count=int(value.get("static_route_count") or 0),
        )

    def likely_changed_from(self, other: "ConfigurationFingerprint | None") -> bool:
        """A fast, structural "did this probably change?" — no config read.

        The hash is the authority for *exact* change; this is the cheap
        pre-check a future module can use to prioritise, never the final word.
        """

        if other is None:
            return True
        if self.config_sha256 and self.config_sha256 == other.config_sha256:
            return False
        return self.to_dict() != other.to_dict()


def fingerprint(config_text: str | None) -> ConfigurationFingerprint | None:
    """Compute a configuration's structural fingerprint. Deterministic."""

    if not config_text or not config_text.strip():
        return None
    text = config_text.replace("\r\n", "\n").replace("\r", "\n")
    host = _HOSTNAME.search(text)
    bgp = _ROUTER_BGP.search(text)
    return ConfigurationFingerprint(
        config_sha256=content_sha256(config_text),
        hostname=host.group(1) if host else None,
        line_count=text.count("\n") + (0 if text.endswith("\n") else 1),
        interface_count=len(_INTERFACE.findall(text)),
        loopback_count=len(_LOOPBACK.findall(text)),
        bgp_neighbor_count=len(_BGP_NEIGHBOR.findall(text)),
        bgp_as=bgp.group(1) if bgp else None,
        ospf_process_count=len(_ROUTER_OSPF.findall(text)),
        ospf_network_count=len(_OSPF_NETWORK.findall(text)),
        acl_count=len(_ACL.findall(text)),
        vrf_count=len(_VRF.findall(text)),
        vlan_count=len(_VLAN.findall(text)),
        static_route_count=len(_STATIC_ROUTE.findall(text)),
    )
