"""The Palo Alto PAN-OS production driver (POLYGLOT Wave 2, Tier 1).

A Palo Alto firewall normalizes exactly the way a FortiGate does: its
addressed interfaces and routing evidence flow into the same canonical
models every router uses, while everything that makes it a *firewall* —
zones, the ordered security rulebase, NAT, IPsec tunnels, virtual
systems (vsys) and HA peering — normalizes into the vendor-neutral
:mod:`founderos_atlas.firewall` models. A PAN-OS "allow" and a FortiOS
"accept" are the same canonical action; downstream never branches on
the vendor.

Zones are read from the logical-interface table (the authoritative
binding of interface → vsys → zone) and enriched by the rulebase. Vsys
contexts come from the same two sources; PAN-OS numbers them ("vsys1")
in the interface table and names rulebase blocks after them.

This driver collects evidence only — no rule judgement, no secrets
(IKE/IPsec keys and certificates are never represented).

Maturity: **EXPERIMENTAL** — TRANSCRIPT VALIDATED only. No live PA
device was available in this environment; every parser is exercised
against sanitized transcripts of realistic PAN-OS 10.2 output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address
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
    ACTION_UNKNOWN,
    CONTEXT_VSYS,
    FirewallEvidence,
    FirewallZone,
    HaPeer,
    NatRule,
    SecurityPolicy,
    VirtualContext,
    VpnTunnel,
)
from founderos_atlas.firewall.models import (
    NAT_DESTINATION,
    NAT_SOURCE,
    NAT_UNKNOWN,
)
from founderos_atlas.routing import (
    BgpSessionObservation,
    OspfAdjacencyObservation,
    routing_metadata,
)

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver


SHOW_SYSTEM_INFO = "show system info"
SHOW_INTERFACE_ALL = "show interface all"
SHOW_SECURITY_POLICY = "show running security-policy"
SHOW_NAT_POLICY = "show running nat-policy"
SHOW_VPN = "show vpn ipsec-sa"
SHOW_HA = "show high-availability state"
SHOW_ROUTES = "show routing route"
SHOW_BGP = "show routing protocol bgp peer"
SHOW_OSPF = "show routing protocol ospf neighbor"
SHOW_LLDP = "show lldp neighbors all"
SHOW_CONFIG = "show config running"

ADAPTER_NAME = "PanOsAdapter"

_KV = re.compile(r"(?m)^(?P<key>[a-z0-9-]+):\s*(?P<value>.+?)\s*$")

# Logical-interface table rows:
# ethernet1/1   16   1   untrust   vr:default   0   203.0.113.42/24
_LOGICAL_ROW = re.compile(
    r"(?m)^(?P<name>\S+)\s+\d+\s+(?P<vsys>\d+)\s+(?P<zone>\S*?)\s+"
    r"(?P<fwd>vr:\S+|N/A)\s+\d+\s+(?P<addr>\S+)\s*$"
)
# Hardware table rows carry state: `ethernet1/1  16  1000/full/up  aa:bb...`
_HW_ROW = re.compile(
    r"(?m)^(?P<name>\S+)\s+\d+\s+\S+/(?P<state>up|down|ukn)\s+\S+\s*$"
)

# Rulebase blocks: `vsys1 { rule-name { from x; ... action allow; } ... }`
_VSYS_BLOCK = re.compile(r"(?m)^(?P<vsys>\S+)\s*\{")
_RULE_HEAD = re.compile(r"(?m)^\s{2}(?P<rule>[^\s{][^{]*?)\s*\{")
_RULE_FIELD = re.compile(r"(?m)^\s+(?P<key>from|to|source|destination)\s+(?P<value>[^;]+);")
_RULE_ACTION = re.compile(r"(?m)^\s+action\s+(?P<action>[a-z-]+);")
_RULE_APPSVC = re.compile(r"(?m)^\s+application/service\s+(?P<value>[^;]+);")
_TRANSLATE = re.compile(r'translate-to\s+"(?P<kind>src|dst):\s*(?P<detail>[^"]+)"')

# IPsec SA table rows: `1  1  198.51.100.9  to-branch(to-branch-gw)  ESP/...`
_IPSEC_ROW = re.compile(
    r"(?m)^\s*\d+\s+\d+\s+(?P<peer>\d+\.\d+\.\d+\.\d+)\s+"
    r"(?P<tunnel>\S+?)\((?P<gw>[^)]*)\)\s+\S+"
)

# HA state.
_HA_MODE = re.compile(r"(?mi)^\s*Mode:\s*(?P<mode>\S+(?:-\S+)?)")
_HA_LOCAL_STATE = re.compile(r"(?mi)^\s*State:\s*(?P<state>\w+)")
_HA_GROUP = re.compile(r"(?mi)^Group\s+(?P<group>\d+):")
_HA_PEER_SERIAL = re.compile(r"(?mi)^\s*Serial Number:\s*(?P<serial>\S+)")
_HA_SYNC = re.compile(r"(?mi)^\s*Running Configuration:\s*(?P<sync>\S+)")

# Route rows inside `VIRTUAL ROUTER: <vr>` sections.
_VR_HEAD = re.compile(r"(?m)^VIRTUAL ROUTER:\s*(?P<vr>\S+)")
_ROUTE_ROW = re.compile(
    r"(?m)^(?P<dest>\d+\.\d+\.\d+\.\d+/\d+)\s+\S+\s+\d+\s+"
    r"(?P<flags>[A-Z?~ ]+?)\s{2,}"
)

# BGP peer blocks.
_BGP_PEER = re.compile(r"(?m)^Peer:\s*(?P<name>\S+)")
_BGP_FIELD = re.compile(r"(?m)^\s+(?P<key>[A-Za-z ]+?):\s*(?P<value>.+?)\s*$")

# OSPF neighbor blocks (one key per line).
_OSPF_ADDR = re.compile(r"(?mi)^\s*neighbor address:\s*(?P<addr>\S+)")
_OSPF_RID = re.compile(r"(?mi)^\s*neighbor router ID:\s*(?P<rid>\S+)")
_OSPF_STATUS = re.compile(r"(?mi)^\s*status:\s*(?P<status>\S+)")
_OSPF_VR = re.compile(r"(?mi)^virtual router:\s*(?P<vr>\S+)")

# LLDP neighbor blocks.
_LLDP_PORT = re.compile(r"(?mi)^Port Name:\s*(?P<port>\S+)")
_LLDP_SYSNAME = re.compile(r"(?mi)^\*?\s*System Name:\s*(?P<name>\S+)")
_LLDP_PORTDESC = re.compile(r"(?mi)^\*?\s*Port Description:\s*(?P<desc>.+?)\s*$")


def _system_info(text: str) -> dict[str, str]:
    return {
        match.group("key"): match.group("value")
        for match in _KV.finditer(text or "")
    }


class PanOsAdapter(DiscoveryAdapter):
    """Parse-only normalization of PAN-OS op-command output."""

    vendor = "paloalto"
    platform_family = "paloalto-panos"
    required_commands = (SHOW_SYSTEM_INFO, SHOW_INTERFACE_ALL)
    optional_commands = (
        SHOW_SECURITY_POLICY, SHOW_NAT_POLICY, SHOW_VPN, SHOW_HA,
        SHOW_ROUTES, SHOW_BGP, SHOW_OSPF, SHOW_LLDP, SHOW_CONFIG,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        info = _system_info(raw_outputs.get(SHOW_SYSTEM_INFO, ""))
        hostname = info.get("hostname")
        if not hostname:
            raise DiscoveryParseError(
                "device identity could not be established from "
                f"{SHOW_SYSTEM_INFO!r}",
                adapter=ADAPTER_NAME, command=SHOW_SYSTEM_INFO, field="hostname",
            )
        management_ip = info.get("ip-address")
        if not _valid_ip(management_ip):
            if _valid_ip(management_ip_hint):
                management_ip = str(management_ip_hint).strip()
            else:
                raise DiscoveryParseError(
                    "no management IP was parsed and no connection address "
                    "was supplied",
                    adapter=ADAPTER_NAME, command=SHOW_SYSTEM_INFO,
                    field="management_ip",
                )
        metadata: dict[str, object] = {
            "model": info.get("model", "unknown"),
            "device_role": "firewall",
            "multi_vsys": info.get("multi-vsys", "off") == "on",
        }
        if info.get("uptime"):
            metadata["uptime"] = info["uptime"]
        return NetworkDevice(
            device_id=f"paloalto-panos:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=info.get("model", "unknown"),
            os_name="PAN-OS",
            os_version=info.get("sw-version", "unknown"),
            serial_number=info.get("serial"),
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        text = raw_outputs.get(SHOW_INTERFACE_ALL, "")
        states = {
            match.group("name"): match.group("state")
            for match in _HW_ROW.finditer(text)
        }
        interfaces: list[NetworkInterface] = []
        for match in _LOGICAL_ROW.finditer(text):
            name = match.group("name")
            if name in ("name", "-------------------"):
                continue
            address = match.group("addr")
            ip, prefix = None, None
            if "/" in address:
                candidate, _, bits = address.partition("/")
                if _valid_ip(candidate):
                    ip, prefix = candidate, int(bits)
            state = states.get(name, "unknown")
            metadata: dict[str, object] = {
                "source_command": SHOW_INTERFACE_ALL,
                "vsys": match.group("vsys"),
            }
            zone = match.group("zone").strip()
            if zone:
                metadata["zone"] = zone
            forwarding = match.group("fwd")
            if forwarding.startswith("vr:"):
                metadata["vrf"] = forwarding[3:]
            if prefix is not None:
                metadata["prefix_length"] = prefix
            interfaces.append(NetworkInterface(
                name=name,
                ip_address=ip,
                status="up" if state == "up" else (
                    "down" if state == "down" else "unknown"
                ),
                metadata=metadata,
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        info = _system_info(raw_outputs.get(SHOW_SYSTEM_INFO, ""))
        local_id = f"paloalto-panos:{info.get('hostname', 'unknown')}"
        neighbors: list[NetworkNeighbor] = []

        # LLDP — link-layer, strongest evidence.
        text = raw_outputs.get(SHOW_LLDP, "")
        for block in re.split(r"(?m)^(?=Port Name:)", text):
            port = _LLDP_PORT.search(block)
            name = _LLDP_SYSNAME.search(block)
            if not (port and name):
                continue
            desc = _LLDP_PORTDESC.search(block)
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=port.group("port"),
                remote_hostname=name.group("name"),
                remote_interface=desc.group("desc") if desc else None,
                protocol="lldp",
                metadata={
                    "observation": "link-layer",
                    "management_endpoint": False,
                    "source_command": SHOW_LLDP,
                },
            ))

        # OSPF adjacencies.
        ospf_text = raw_outputs.get(SHOW_OSPF, "")
        vr = _OSPF_VR.search(ospf_text)
        for block in re.split(r"(?m)^\s*$", ospf_text):
            addr = _OSPF_ADDR.search(block)
            rid = _OSPF_RID.search(block)
            if not (addr and rid):
                continue
            status = _OSPF_STATUS.search(block)
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface="ospf",
                remote_hostname=rid.group("rid"),
                protocol="ospf",
                metadata={
                    "observation": "routing-adjacency",
                    "router_id": rid.group("rid"),
                    "adjacency_address": addr.group("addr"),
                    "ospf_state": (
                        status.group("status") if status else "unknown"
                    ),
                    "vrf": vr.group("vr") if vr else "default",
                    "address_family": "ipv4",
                    "management_endpoint": False,
                    "source_command": SHOW_OSPF,
                },
            ))
        return tuple(neighbors)


def _bgp_observations(text: str) -> tuple[BgpSessionObservation, ...]:
    sessions: list[BgpSessionObservation] = []
    for block in re.split(r"(?m)^(?=Peer:)", text or ""):
        head = _BGP_PEER.search(block)
        if not head:
            continue
        fields = {
            match.group("key").strip().casefold(): match.group("value")
            for match in _BGP_FIELD.finditer(block)
        }
        address = fields.get("peer address", "").rsplit(":", 1)[0]
        state_word = fields.get("peer status", "unknown").split(",", 1)[0]
        state = state_word.strip().casefold()
        sessions.append(BgpSessionObservation(
            peer_address=address or head.group("name"),
            remote_as=str(fields.get("remote as", "unknown")),
            local_as=None,
            state=state if state in (
                "established", "active", "idle", "connect", "opensent",
                "openconfirm",
            ) else "unknown",
            vrf=fields.get("virtual router", "default"),
            router_id=fields.get("peer router id"),
            source_command=SHOW_BGP,
        ))
    return tuple(sessions)


class PanOsDriver(ProductionDriver):
    """Palo Alto PAN-OS, held to the production contract."""

    platform_id = "paloalto-panos"
    display_name = "Palo Alto PAN-OS"
    vendor = "paloalto"
    probe_command = SHOW_SYSTEM_INFO
    banner_fingerprints = (r"pan-?os", r"palo\s*alto")
    prompt_fingerprints = (r"@[\w.-]+> ?$",)
    netmiko_device_type = "paloalto_panos"
    session_setup = ("set cli pager off", "set cli config-output-format set")
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        text = probe_output or ""
        return bool(
            re.search(r"(?m)^sw-version:\s*\d", text)
            and re.search(r"(?m)^model:\s*PA-", text)
        ) or "PAN-OS" in text

    @property
    def adapter(self) -> PanOsAdapter:
        return PanOsAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (SHOW_SYSTEM_INFO,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (SHOW_INTERFACE_ALL,),
                        required=True, tier=TIER_FAST),
            CommandSpec("zones", (SHOW_INTERFACE_ALL,), tier=TIER_FAST,
                        limitation=(
                            "zones are read from the logical-interface "
                            "table; unbound zones appear only via policy"
                        )),
            CommandSpec("security-policy", (SHOW_SECURITY_POLICY,)),
            CommandSpec("nat", (SHOW_NAT_POLICY,)),
            CommandSpec("vpn", (SHOW_VPN,)),
            CommandSpec("ha", (SHOW_HA,)),
            CommandSpec("virtual-firewalls", (SHOW_SYSTEM_INFO,),
                        limitation=(
                            "vsys inventory is derived from the interface "
                            "table and rulebase blocks"
                        )),
            CommandSpec(caps.LLDP, (SHOW_LLDP,)),
            CommandSpec(caps.ROUTES, (SHOW_ROUTES,)),
            CommandSpec(caps.BGP, (SHOW_BGP,)),
            CommandSpec(caps.OSPF, (SHOW_OSPF,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_CONFIG,), tier=TIER_DEEP),
        )

    def rejects(self, output: str) -> bool:
        folded = (output or "").strip().casefold()
        if not folded:
            return False
        return (
            folded.startswith("unknown command")
            or "invalid syntax" in folded[:200]
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)

        evidence = _build_firewall_evidence(raw, discovery)
        if not evidence.is_empty:
            metadata["firewall_evidence"] = evidence.to_dict()

        sessions = _bgp_observations(raw.get(SHOW_BGP, ""))
        ospf = tuple(
            OspfAdjacencyObservation(
                neighbor_router_id=str(item.metadata.get("router_id")),
                adjacency_address=item.metadata.get("adjacency_address"),
                local_interface=item.local_interface,
                state=str(item.metadata.get("ospf_state") or "unknown"),
                vrf=str(item.metadata.get("vrf") or "default"),
                address_family="ipv4",
                source_command=SHOW_OSPF,
            )
            for item in discovery.result.neighbors if item.protocol == "ospf"
        )
        if ospf or sessions:
            metadata["routing_evidence"] = routing_metadata(
                ospf=ospf, bgp=sessions
            )
        metadata["route_count"] = len(
            _ROUTE_ROW.findall(raw.get(SHOW_ROUTES, ""))
        )
        vrfs = sorted(set(_VR_HEAD.findall(raw.get(SHOW_ROUTES, ""))))
        if vrfs:
            metadata["vrfs"] = tuple(vrfs)

        bgp_neighbors = tuple(
            NetworkNeighbor(
                local_device_id=discovery.result.device.device_id,
                local_interface="bgp",
                remote_hostname=item.peer_address,
                protocol="bgp",
                metadata={
                    "observation": "protocol-peer", **item.to_dict(),
                    "management_endpoint": False,
                },
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


def _build_firewall_evidence(
    raw: Mapping[str, str], discovery: DriverDiscovery
) -> FirewallEvidence:
    zones = _zones_from_interfaces(discovery)
    policies = _parse_rulebase(raw.get(SHOW_SECURITY_POLICY, ""))
    nat = _parse_nat(raw.get(SHOW_NAT_POLICY, ""))
    vpns = _parse_ipsec(raw.get(SHOW_VPN, ""))
    contexts = _vsys_contexts(discovery, zones, policies)
    ha_peers, ha_mode = _parse_ha(raw.get(SHOW_HA, ""))
    sources = tuple(
        cmd for cmd in (
            SHOW_INTERFACE_ALL, SHOW_SECURITY_POLICY, SHOW_NAT_POLICY,
            SHOW_VPN, SHOW_HA,
        )
        if raw.get(cmd, "").strip()
    )
    return FirewallEvidence(
        zones=zones, security_policies=policies, nat_rules=nat, vpns=vpns,
        virtual_contexts=contexts, ha_peers=ha_peers, ha_mode=ha_mode,
        source_commands=sources,
    )


def _zones_from_interfaces(discovery: DriverDiscovery) -> tuple[FirewallZone, ...]:
    bound: dict[tuple[str, str], list[str]] = {}
    for interface in discovery.result.interfaces:
        zone = interface.metadata.get("zone")
        if not zone:
            continue
        vsys = f"vsys{interface.metadata.get('vsys')}" if (
            interface.metadata.get("vsys") not in (None, "0")
        ) else None
        bound.setdefault((str(zone), vsys or ""), []).append(interface.name)
    return tuple(
        FirewallZone(
            name=zone,
            interfaces=tuple(sorted(names)),
            virtual_context=vsys or None,
        )
        for (zone, vsys), names in sorted(bound.items())
    )


def _panos_action(word: str) -> str:
    folded = (word or "").strip().casefold()
    if folded == "allow":
        return ACTION_ALLOW
    if folded in ("deny", "drop", "reset-client", "reset-server", "reset-both"):
        return ACTION_DENY
    return ACTION_UNKNOWN


def _split_values(value: str) -> tuple[str, ...]:
    cleaned = value.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return tuple(part for part in cleaned.split() if part)


def _parse_rulebase(text: str) -> tuple[SecurityPolicy, ...]:
    policies: list[SecurityPolicy] = []
    for vsys_block in re.split(r"(?m)^(?=\S+\s*\{)", text or ""):
        vsys_match = _VSYS_BLOCK.match(vsys_block)
        if not vsys_match:
            continue
        vsys = vsys_match.group("vsys")
        for rule_block in re.split(r"(?m)^\s{2}(?=[^\s{])", vsys_block)[1:]:
            head = re.match(r"(?P<rule>[^{;]+?)\s*\{", rule_block)
            if not head:
                continue
            rule = head.group("rule").strip()
            fields: dict[str, tuple[str, ...]] = {}
            for match in _RULE_FIELD.finditer(rule_block):
                fields.setdefault(
                    match.group("key"), _split_values(match.group("value"))
                )
            action = _RULE_ACTION.search(rule_block)
            appsvc = _RULE_APPSVC.search(rule_block)
            applications: tuple[str, ...] = ()
            services: tuple[str, ...] = ()
            if appsvc:
                for token in _split_values(appsvc.group("value")):
                    application, _, service = token.partition("/")
                    if application and application != "any":
                        applications += (application,)
                    if service and service != "any/any/any":
                        services += (service,)
            policies.append(SecurityPolicy(
                policy_id=f"{vsys}:{rule}",
                name=rule,
                from_zones=fields.get("from", ()),
                to_zones=fields.get("to", ()),
                sources=fields.get("source", ()),
                destinations=fields.get("destination", ()),
                services=services,
                applications=applications,
                action=_panos_action(action.group("action") if action else ""),
                enabled=True,
                virtual_context=vsys,
            ))
    return tuple(policies)


def _parse_nat(text: str) -> tuple[NatRule, ...]:
    rules: list[NatRule] = []
    for vsys_block in re.split(r"(?m)^(?=\S+\s*\{)", text or ""):
        vsys_match = _VSYS_BLOCK.match(vsys_block)
        if not vsys_match:
            continue
        vsys = vsys_match.group("vsys")
        for rule_block in re.split(r"(?m)^\s{2}(?=[^\s{])", vsys_block)[1:]:
            head = re.match(r"(?P<rule>[^{;]+?)\s*\{", rule_block)
            if not head:
                continue
            rule = head.group("rule").strip()
            translate = _TRANSLATE.search(rule_block)
            nat_type = NAT_UNKNOWN
            translated_source = translated_destination = None
            if translate:
                detail = translate.group("detail").split()[0:2]
                target = detail[-1] if detail else None
                if translate.group("kind") == "src":
                    nat_type = NAT_SOURCE
                    translated_source = target
                else:
                    nat_type = NAT_DESTINATION
                    translated_destination = target
            fields: dict[str, tuple[str, ...]] = {}
            for match in _RULE_FIELD.finditer(rule_block):
                fields.setdefault(
                    match.group("key"), _split_values(match.group("value"))
                )
            rules.append(NatRule(
                rule_id=f"{vsys}:{rule}",
                name=rule,
                nat_type=nat_type,
                original_sources=fields.get("source", ()),
                original_destinations=fields.get("destination", ()),
                translated_source=translated_source,
                translated_destination=translated_destination,
                virtual_context=vsys,
            ))
    return tuple(rules)


def _parse_ipsec(text: str) -> tuple[VpnTunnel, ...]:
    tunnels: list[VpnTunnel] = []
    for match in _IPSEC_ROW.finditer(text or ""):
        # A tunnel with an installed IPsec SA row IS up — that is what the
        # SA table lists. Tunnels without SAs simply do not appear here;
        # absence is honest "no evidence", never a guessed "down".
        tunnels.append(VpnTunnel(
            name=match.group("tunnel"),
            tunnel_type="ipsec",
            remote_gateway=match.group("peer"),
            status="up",
        ))
    return tuple(tunnels)


def _vsys_contexts(
    discovery: DriverDiscovery, zones, policies
) -> tuple[VirtualContext, ...]:
    info = _system_info(
        discovery.raw_outputs.get(SHOW_SYSTEM_INFO, "")
    )
    names: set[str] = set()
    for interface in discovery.result.interfaces:
        vsys = interface.metadata.get("vsys")
        if vsys not in (None, "0"):
            names.add(f"vsys{vsys}")
    for policy in policies:
        if policy.virtual_context:
            names.add(policy.virtual_context)
    if not names and info.get("multi-vsys") != "on":
        return ()
    contexts: list[VirtualContext] = []
    for name in sorted(names):
        contexts.append(VirtualContext(
            name=name,
            context_type=CONTEXT_VSYS,
            zone_count=sum(1 for z in zones if z.virtual_context == name),
            policy_count=sum(
                1 for p in policies if p.virtual_context == name
            ),
            interface_count=sum(
                1 for i in discovery.result.interfaces
                if f"vsys{i.metadata.get('vsys')}" == name
            ),
        ))
    return tuple(contexts)


def _parse_ha(text: str):
    if not (text or "").strip():
        return (), None
    mode_match = _HA_MODE.search(text)
    mode_word = (mode_match.group("mode").casefold() if mode_match else "")
    mode = {
        "active-passive": "a-p",
        "active-active": "a-a",
    }.get(mode_word, mode_word or None)
    group = _HA_GROUP.search(text)
    sync = _HA_SYNC.search(text)
    states = _HA_LOCAL_STATE.findall(text)
    peers: list[HaPeer] = []
    local_state = states[0].casefold() if states else "unknown"
    peer_state = states[1].casefold() if len(states) > 1 else "unknown"
    peer_serial = _HA_PEER_SERIAL.search(text)
    peers.append(HaPeer(
        role=local_state, mode=mode,
        status=(
            "in-sync" if sync and sync.group("sync") == "synchronized"
            else "unknown"
        ),
        group=group.group("group") if group else None,
    ))
    if len(states) > 1:
        peers.append(HaPeer(
            role=peer_state, mode=mode,
            peer_serial=peer_serial.group("serial") if peer_serial else None,
            status=(
                "in-sync" if sync and sync.group("sync") == "synchronized"
                else "unknown"
            ),
            group=group.group("group") if group else None,
        ))
    return tuple(peers), mode


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
