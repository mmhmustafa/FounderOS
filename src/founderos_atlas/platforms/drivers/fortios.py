"""The Fortinet FortiOS production driver (PR-056, POLYGLOT Wave 2, Tier 1).

A FortiGate is a firewall first and a router second. Its addressed
interfaces and routing table normalize into the same canonical models
every platform uses, so Topology, Path Intelligence and Prediction see a
FortiGate as an ordinary layer-3 node with no vendor knowledge. What
makes it a *firewall* — security zones, an ordered policy set, NAT, IPsec
tunnels, VDOMs and HA peering — is collected as first-class evidence and
normalized into the vendor-neutral :mod:`founderos_atlas.firewall`
models, stamped into ``device.metadata["firewall_evidence"]`` where
Policy and the Evidence Explorer already read normalized facts.

This driver collects evidence only. It does not analyse or judge the
rule set (a default-deny posture is a reported fact, never a verdict),
and it never touches a secret: VPN pre-shared keys and certificates are
not represented in the firewall model.

Maturity: **EXPERIMENTAL** — TRANSCRIPT VALIDATED only. No live FortiGate
was available in this environment; every parser is exercised against
sanitized transcripts of realistic FortiOS 7.2 output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address, ip_network
import re

from founderos_atlas.discovery.adapter import DiscoveryAdapter
from founderos_atlas.discovery.exceptions import DiscoveryParseError
from founderos_atlas.discovery.models import (
    NetworkDevice,
    NetworkInterface,
    NetworkNeighbor,
)
from founderos_atlas.firewall import (
    ACTION_ALLOW,
    ACTION_DENY,
    CONTEXT_VDOM,
    FirewallEvidence,
    FirewallZone,
    HaPeer,
    NatRule,
    SecurityPolicy,
    VirtualContext,
    VpnTunnel,
)
from founderos_atlas.firewall.models import NAT_DESTINATION, NAT_SOURCE
from founderos_atlas.routing import (
    OspfAdjacencyObservation,
    bgp_sessions_from_summary,
    routing_metadata,
)
from founderos_atlas.routing.table import route_table_dicts
from founderos_atlas.routing.policy import (
    parse_fortios_policy_routes,
    policy_route_dicts,
)

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver


GET_SYSTEM_STATUS = "get system status"
GET_SYSTEM_INTERFACE = "get system interface"
SHOW_ZONE = "show system zone"
SHOW_POLICY = "show firewall policy"
SHOW_VIP = "show firewall vip"
GET_VPN = "get vpn ipsec tunnel summary"
GET_HA = "get system ha status"
SHOW_VDOM = "show vdom"
GET_ROUTES = "get router info routing-table all"
SHOW_STATIC = "show router static"
SHOW_POLICY_ROUTES = "show router policy"
GET_BGP = "get router info bgp summary"
GET_OSPF = "get router info ospf neighbor"
SHOW_RUNNING = "show"

ADAPTER_NAME = "FortiOSAdapter"
UNKNOWN = "unknown"

# `Version: FortiGate-100F v7.2.5,build1517,230608 (GA.F)`
_VERSION = re.compile(
    r"(?m)^Version:\s*(?P<model>FortiGate-\S+)\s+v(?P<version>[0-9.]+)"
)
_SERIAL = re.compile(r"(?m)^Serial-Number:\s*(?P<serial>\S+)")
_HOSTNAME = re.compile(r"(?m)^Hostname:\s*(?P<host>\S+)")
_VDOM_MODE = re.compile(r"(?mi)^Virtual domain configuration:\s*(?P<mode>\S+)")

# `get system interface` prints per-interface blocks:
# == [ port1 ]
#         name: port1   mode: static    ip: 172.20.20.34 255.255.255.0   status: up ...
_IFACE_HEAD = re.compile(r"^==\s*\[\s*(?P<name>\S+)\s*\]")
_IFACE_IP = re.compile(
    r"ip:\s*(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<mask>\d+\.\d+\.\d+\.\d+)"
)
_IFACE_STATUS = re.compile(r"status:\s*(?P<status>up|down)", re.IGNORECASE)

# `show system zone` config blocks.
_ZONE_EDIT = re.compile(r'(?m)^\s*edit\s+"(?P<zone>[^"]+)"')
_ZONE_INTF = re.compile(r'(?m)^\s*set\s+interface\s+(?P<ifaces>.+)$')

# BGP summary (Cisco-shaped) reused via routing.bgp_sessions_from_summary.
_OSPF_ROW = re.compile(
    r"(?m)^\s*(?P<rid>\d+\.\d+\.\d+\.\d+)\s+\d+\s+(?P<state>\S+)\s+\S+\s+"
    r"(?P<addr>\d+\.\d+\.\d+\.\d+)\s+(?P<intf>\S+)\s*$"
)

# HA status.
_HA_MODE = re.compile(r"(?mi)^Mode:\s*HA\s+(?P<mode>\S+)")
_HA_GROUP = re.compile(r"(?mi)^Group Name:\s*(?P<group>.+?)\s*$")
_HA_MEMBER = re.compile(
    r"(?mi)^(?P<role>Master|Slave)\s*:\s*(?P<name>[^,]+),\s*(?P<serial>\S+)"
)


class FortiOSAdapter(DiscoveryAdapter):
    """Parse-only normalization of FortiOS CLI output."""

    vendor = "fortinet"
    platform_family = "fortinet-fortios"
    required_commands = (GET_SYSTEM_STATUS, GET_SYSTEM_INTERFACE)
    optional_commands = (
        SHOW_ZONE, SHOW_POLICY, SHOW_VIP, GET_VPN, GET_HA, SHOW_VDOM,
        GET_ROUTES, SHOW_STATIC, GET_BGP, GET_OSPF, SHOW_RUNNING,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        status = raw_outputs.get(GET_SYSTEM_STATUS, "")
        version = _VERSION.search(status)
        host = _HOSTNAME.search(status)
        if version is None or host is None:
            raise DiscoveryParseError(
                "device identity could not be established from "
                f"{GET_SYSTEM_STATUS!r}",
                adapter=ADAPTER_NAME, command=GET_SYSTEM_STATUS, field="hostname",
            )
        hostname = host.group("host")
        serial = _SERIAL.search(status)
        model = version.group("model")
        management_ip, warnings = self._management_ip(
            raw_outputs.get(GET_SYSTEM_INTERFACE, ""), management_ip_hint
        )
        vdom_mode = _VDOM_MODE.search(status)
        metadata: dict[str, object] = {
            "model": model,
            "device_role": "firewall",
        }
        if vdom_mode:
            metadata["vdom_mode"] = vdom_mode.group("mode")
        if warnings:
            metadata["warnings"] = tuple(warnings)
        return NetworkDevice(
            device_id=f"fortinet-fortios:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model,
            os_name="FortiOS",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces: list[NetworkInterface] = []
        for name, ip, prefix, status in _iter_interfaces(
            raw_outputs.get(GET_SYSTEM_INTERFACE, "")
        ):
            metadata: dict[str, object] = {"source_command": GET_SYSTEM_INTERFACE}
            if prefix is not None:
                metadata["prefix_length"] = prefix
            interfaces.append(NetworkInterface(
                name=name,
                ip_address=ip,
                status=status,
                metadata=metadata,
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        host = _HOSTNAME.search(raw_outputs.get(GET_SYSTEM_STATUS, ""))
        local_id = (
            f"fortinet-fortios:{host.group('host')}" if host
            else "fortinet-fortios:unknown"
        )
        neighbors: list[NetworkNeighbor] = []
        for match in _OSPF_ROW.finditer(raw_outputs.get(GET_OSPF, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("intf"),
                remote_hostname=match.group("rid"),
                protocol="ospf",
                metadata={
                    "observation": "routing-adjacency",
                    "router_id": match.group("rid"),
                    "adjacency_address": match.group("addr"),
                    "ospf_state": match.group("state"),
                    "vrf": "default",
                    "address_family": "ipv4",
                    "management_endpoint": False,
                    "source_command": GET_OSPF,
                },
            ))
        return tuple(neighbors)

    def _management_ip(self, text: str, hint: str | None):
        warnings: list[str] = []
        entries = [
            (name, ip) for name, ip, _p, _s in _iter_interfaces(text) if ip
        ]
        wanted = str(hint).strip() if hint else None
        for name, ip in entries:
            if wanted and ip == wanted:
                return ip, warnings
        if entries:
            return entries[0][1], warnings
        if _valid_ip(hint):
            warnings.append(
                "management IP was not parsed from interface addressing; "
                "using the connection address as a deterministic fallback"
            )
            return str(hint).strip(), warnings
        raise DiscoveryParseError(
            "no management IP was parsed and no connection address was supplied",
            adapter=ADAPTER_NAME, command=GET_SYSTEM_INTERFACE,
            field="management_ip",
        )


class FortiOSDriver(ProductionDriver):
    """Fortinet FortiOS, held to the production contract."""

    platform_id = "fortinet-fortios"
    display_name = "Fortinet FortiOS"
    vendor = "fortinet"
    probe_command = GET_SYSTEM_STATUS
    banner_fingerprints = (r"fortinet", r"fortigate")
    prompt_fingerprints = (r"[\w-]+ [#$] ?$", r"\$ $")
    netmiko_device_type = "fortinet"
    # No session setup: `config system console` would enter a CONFIG scope,
    # which the read-only transport policy rightly refuses. netmiko's
    # "fortinet" personality already disables output paging on connect.
    session_setup = ()
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        text = probe_output or ""
        return bool(
            re.search(r"(?m)^Version:\s*FortiGate", text)
            or re.search(r"FortiOS", text)
        )

    @property
    def adapter(self) -> FortiOSAdapter:
        return FortiOSAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (GET_SYSTEM_STATUS,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (GET_SYSTEM_INTERFACE,),
                        required=True, tier=TIER_FAST),
            CommandSpec("zones", (SHOW_ZONE,), tier=TIER_FAST),
            CommandSpec("security-policy", (SHOW_POLICY,)),
            CommandSpec("nat", (SHOW_VIP,)),
            CommandSpec("vpn", (GET_VPN,)),
            CommandSpec("ha", (GET_HA,)),
            CommandSpec("virtual-firewalls", (SHOW_VDOM,)),
            CommandSpec(caps.ROUTES, (GET_ROUTES,)),
            CommandSpec(caps.STATIC_ROUTES, (SHOW_STATIC,)),
            CommandSpec(caps.POLICY_ROUTES, (SHOW_POLICY_ROUTES,)),
            CommandSpec(caps.BGP, (GET_BGP,)),
            CommandSpec(caps.OSPF, (GET_OSPF,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_RUNNING,), tier=TIER_DEEP),
        )

    def rejects(self, output: str) -> bool:
        folded = (output or "").strip().casefold()
        if not folded:
            return False
        return (
            folded.startswith("command fail")
            or "unknown action" in folded[:80]
            or "command parse error" in folded[:80]
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)

        evidence = _build_firewall_evidence(raw)
        if not evidence.is_empty:
            metadata["firewall_evidence"] = evidence.to_dict()

        # Routing evidence rides the same canonical channel every router uses.
        sessions = bgp_sessions_from_summary(raw.get(GET_BGP, ""), source_command=GET_BGP)
        ospf = tuple(
            OspfAdjacencyObservation(
                neighbor_router_id=str(item.metadata.get("router_id")),
                adjacency_address=item.metadata.get("adjacency_address"),
                local_interface=item.local_interface,
                state=str(item.metadata.get("ospf_state") or "unknown"),
                vrf="default", address_family="ipv4", source_command=GET_OSPF,
            )
            for item in discovery.result.neighbors if item.protocol == "ospf"
        )
        if ospf or sessions:
            metadata["routing_evidence"] = routing_metadata(ospf=ospf, bgp=sessions)
        if sessions:
            metadata["bgp_peers"] = tuple(
                tuple(sorted({"peer": s.peer_address, "remote_as": s.remote_as}.items()))
                for s in sessions
            )
        metadata["route_count"] = _count_routes(raw.get(GET_ROUTES, ""))
        # FortiOS prints the shared `show ip route` grammar, so the
        # canonical parser reads it — no FortiOS-specific reader.
        routing_table = route_table_dicts(raw.get(GET_ROUTES, ""))
        if routing_table:
            metadata["routing_table"] = routing_table

        # Policy routes decide a flow BEFORE the table above is consulted,
        # so a forwarding verdict that ignores them can be confidently
        # wrong. Recorded only when the command actually answered: a
        # FortiOS without PBR returns nothing here, and that silence must
        # not be stored as though Atlas had read a policy set.
        if SHOW_POLICY_ROUTES in raw:
            policy_routes = policy_route_dicts(parse_fortios_policy_routes(
                raw.get(SHOW_POLICY_ROUTES, ""),
                source_command=SHOW_POLICY_ROUTES,
            ))
            metadata["policy_routes"] = policy_routes
            # An empty tuple here is a FACT — asked, and there are none.
            # The engine needs that apart from "never asked", which is the
            # key being absent altogether.
            metadata["policy_routes_captured"] = True

        bgp_neighbors = tuple(
            NetworkNeighbor(
                local_device_id=discovery.result.device.device_id,
                local_interface="bgp", remote_hostname=item.peer_address,
                protocol="bgp",
                metadata={"observation": "protocol-peer", **item.to_dict(),
                          "management_endpoint": False},
            )
            for item in sessions
        )
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
            neighbors=(*discovery.result.neighbors, *bgp_neighbors),
        )
        return replace(discovery, result=result)


# -- firewall evidence normalization ------------------------------------------


def _build_firewall_evidence(raw: Mapping[str, str]) -> FirewallEvidence:
    zones = _parse_zones(raw.get(SHOW_ZONE, ""))
    policies = _parse_policies(raw.get(SHOW_POLICY, ""))
    nat = _parse_vips(raw.get(SHOW_VIP, "")) + _nat_from_policies(
        raw.get(SHOW_POLICY, "")
    )
    vpns = _parse_vpns(raw.get(GET_VPN, ""))
    contexts = _parse_vdoms(raw.get(SHOW_VDOM, ""), zones, policies)
    ha_peers, ha_mode = _parse_ha(raw.get(GET_HA, ""))
    sources = tuple(
        cmd for cmd in (SHOW_ZONE, SHOW_POLICY, SHOW_VIP, GET_VPN, GET_HA, SHOW_VDOM)
        if raw.get(cmd, "").strip()
    )
    return FirewallEvidence(
        zones=zones, security_policies=policies, nat_rules=nat, vpns=vpns,
        virtual_contexts=contexts, ha_peers=ha_peers, ha_mode=ha_mode,
        source_commands=sources,
    )


def _parse_zones(text: str) -> tuple[FirewallZone, ...]:
    zones: list[FirewallZone] = []
    current: str | None = None
    for line in (text or "").splitlines():
        edit = _ZONE_EDIT.match(line)
        if edit:
            current = edit.group("zone")
            zones.append(FirewallZone(name=current, interfaces=()))
            continue
        intf = _ZONE_INTF.match(line)
        if intf and zones:
            names = tuple(re.findall(r'"([^"]+)"', intf.group("ifaces")))
            zones[-1] = replace(zones[-1], interfaces=names)
    return tuple(zones)


def _fortios_action(word: str) -> str:
    folded = (word or "").strip().casefold()
    if folded == "accept":
        return ACTION_ALLOW
    if folded in ("deny", "reject", "drop"):
        return ACTION_DENY
    return ACTION_ALLOW  # a FortiGate policy with no explicit action permits


def _parse_policies(text: str) -> tuple[SecurityPolicy, ...]:
    policies: list[SecurityPolicy] = []
    for block in re.split(r"(?m)^\s*edit\s+", text or "")[1:]:
        pid_match = re.match(r"(\d+)", block)
        if not pid_match:
            continue
        pid = pid_match.group(1)

        def _field(key: str) -> tuple[str, ...]:
            m = re.search(rf'(?m)^\s*set\s+{key}\s+(?P<v>.+)$', block)
            if not m:
                return ()
            return tuple(re.findall(r'"([^"]+)"', m.group("v"))) or (
                tuple(m.group("v").split())
            )

        name = _field("name")
        action_m = re.search(r"(?m)^\s*set\s+action\s+(\S+)", block)
        status_m = re.search(r"(?m)^\s*set\s+status\s+(\S+)", block)
        log_m = re.search(r"(?m)^\s*set\s+logtraffic\s+(\S+)", block)
        policies.append(SecurityPolicy(
            policy_id=pid,
            name=name[0] if name else None,
            from_zones=_field("srcintf"),
            to_zones=_field("dstintf"),
            sources=_field("srcaddr"),
            destinations=_field("dstaddr"),
            services=_field("service"),
            action=_fortios_action(action_m.group(1) if action_m else "accept"),
            log=(log_m.group(1).casefold() != "disable") if log_m else None,
            enabled=not (status_m and status_m.group(1).casefold() == "disable"),
        ))
    return tuple(policies)


def _nat_from_policies(text: str) -> tuple[NatRule, ...]:
    rules: list[NatRule] = []
    for block in re.split(r"(?m)^\s*edit\s+", text or "")[1:]:
        pid = re.match(r"(\d+)", block)
        if pid and re.search(r"(?m)^\s*set\s+nat\s+enable", block):
            rules.append(NatRule(
                rule_id=f"policy-{pid.group(1)}",
                nat_type=NAT_SOURCE,
                name="policy source NAT",
            ))
    return tuple(rules)


def _parse_vips(text: str) -> tuple[NatRule, ...]:
    rules: list[NatRule] = []
    for block in re.split(r"(?m)^\s*edit\s+", text or "")[1:]:
        name_m = re.match(r'"([^"]+)"', block)
        ext = re.search(r"(?m)^\s*set\s+extip\s+(\S+)", block)
        mapped = re.search(r"(?m)^\s*set\s+mappedip\s+\"?(\S+?)\"?\s*$", block)
        if not name_m:
            continue
        rules.append(NatRule(
            rule_id=f"vip-{name_m.group(1)}",
            name=name_m.group(1),
            nat_type=NAT_DESTINATION,
            original_destinations=(ext.group(1),) if ext else (),
            translated_destination=mapped.group(1) if mapped else None,
        ))
    return tuple(rules)


def _parse_vpns(text: str) -> tuple[VpnTunnel, ...]:
    tunnels: list[VpnTunnel] = []
    for line in (text or "").splitlines():
        # `'to-branch' 198.51.100.1:0  selectors 1  rx 1024  tx 2048`
        m = re.match(
            r"\s*'(?P<name>[^']+)'\s+(?P<gw>\d+\.\d+\.\d+\.\d+):\d+\s+"
            r"selectors\s+(?P<sel>\d+)", line
        )
        if not m:
            continue
        # A tunnel with at least one installed selector is operationally up;
        # zero selectors means no SA is installed (down). Documented heuristic
        # from the summary output, which carries no explicit status word.
        status = "up" if int(m.group("sel")) >= 1 else "down"
        tunnels.append(VpnTunnel(
            name=m.group("name"),
            tunnel_type="ipsec",
            remote_gateway=m.group("gw"),
            status=status,
        ))
    return tuple(tunnels)


def _parse_vdoms(
    text: str, zones, policies
) -> tuple[VirtualContext, ...]:
    names = re.findall(r'(?m)^\s*edit\s+"?(?P<vd>[A-Za-z0-9_.-]+)"?\s*$', text or "")
    contexts: list[VirtualContext] = []
    for name in names:
        contexts.append(VirtualContext(
            name=name, context_type=CONTEXT_VDOM,
            zone_count=len(zones), policy_count=len(policies),
        ))
    return tuple(contexts)


def _parse_ha(text: str):
    mode_m = _HA_MODE.search(text or "")
    group_m = _HA_GROUP.search(text or "")
    mode = mode_m.group("mode").lower() if mode_m else None
    peers: list[HaPeer] = []
    for m in _HA_MEMBER.finditer(text or ""):
        peers.append(HaPeer(
            role="primary" if m.group("role") == "Master" else "secondary",
            mode=mode,
            peer_name=m.group("name").strip(),
            peer_serial=m.group("serial").strip(),
            status="in-sync",
            group=group_m.group("group") if group_m else None,
        ))
    return tuple(peers), mode


def _iter_interfaces(text: str):
    """(name, ip, prefix, status) per interface from `get system interface`."""

    name = None
    for line in (text or "").splitlines():
        head = _IFACE_HEAD.match(line.strip())
        if head:
            name = head.group("name")
            continue
        if name is None:
            continue
        ip_m = _IFACE_IP.search(line)
        status_m = _IFACE_STATUS.search(line)
        if ip_m or status_m:
            ip = ip_m.group("ip") if ip_m else None
            prefix = None
            if ip_m:
                try:
                    prefix = ip_network(
                        f"0.0.0.0/{ip_m.group('mask')}"
                    ).prefixlen
                except ValueError:
                    prefix = None
            status = (status_m.group("status").lower() if status_m else "unknown")
            yield name, ip, prefix, status
            name = None


def _count_routes(text: str) -> int:
    """Route lines only.

    A leading capital alone also matched the table's own header — "Routing
    table for VRF=0" begins with an R — so every FortiGate reported one
    route more than it had. A route line carries a prefix; the header does
    not.
    """

    return len([
        line for line in (text or "").splitlines()
        if re.match(r"^\s*[A-Z*].*\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b", line)
    ])


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
