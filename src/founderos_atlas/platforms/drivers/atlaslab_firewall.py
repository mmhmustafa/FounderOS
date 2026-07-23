"""The AtlasLab firewall platform driver (PR-048).

A perimeter firewall is router-shaped where it matters — it owns addressed
interfaces and a routing table — so identity, interfaces and routes normalize
into the same canonical models every other platform uses. What makes it a
*firewall* rather than a small router is the one thing no other platform in the
estate reports: an enforced FORWARD policy and an ordered rule set, carrying
live packet and byte counters.

That rule set is collected as first-class evidence and summarized into canonical
metadata, so Policy can reason about it (a chain whose default policy is DROP is
a compliance fact, not a guess) without any consumer learning that iptables
exists.

The firewall runs no routing protocol, so it has no OSPF or BGP adjacency to
report — but the lab images run lldpd, so each of its legs carries the peer
naming itself. ``parse_neighbors`` normalizes exactly that and nothing more:
deriving neighbors from the routing table would still be inventing adjacencies
the device never claimed.
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
from founderos_atlas.routing.table import iproute2_route_dicts
from founderos_atlas.routing.policy import (
    parse_iproute2_rule_commands,
    policy_route_dicts,
)

from ..base import (
    CAP_COLLECTED,
    CapabilitySpec,
    CapabilityStatus,
    DriverDiscovery,
    PlatformDriver,
)
from .lldpd import parse_lldp_neighbors


SHOW_VERSION = "show version"
SHOW_INTERFACES = "show interfaces"
SHOW_ROUTE = "show route"
SHOW_FIREWALL_RULES = "show firewall rules"
SHOW_RUNNING = "show running-config"
SHOW_LLDP = "show lldp neighbors"
SHOW_LOG = "show log"

ADAPTER_NAME = "AtlasLabFirewallAdapter"
UNKNOWN = "unknown"

# `AtlasLab firewall (delhi-fw) on Linux 6.18.33.2-microsoft-standard-WSL2`
# The lab images report identity in FRRouting's own shape, so one pattern
# serves every platform Atlas drives and the hostname is *observed* rather
# than constructed from a site comment.
_IDENTITY = re.compile(
    r"^AtlasLab firewall\s*\((?P<hostname>[^)]+)\)\s*on\s+(?P<os>.+?)\s*$",
    re.MULTILINE,
)
_PRETTY_NAME = re.compile(r'PRETTY_NAME="(?P<name>[^"]+)"')

# `eth0@if378       UP             172.20.20.38/24 3fff:...::26/64 fe80::.../64`
# (`ip -br addr`). The `@ifNNN` suffix is the peer's kernel index inside the
# lab host and changes on every redeploy, so it is stripped: an interface is
# `eth0`, not `eth0@if378`.
_INTERFACE = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?:@if\d+)?\s+(?P<state>\S+)\s+(?P<addresses>.*)$"
)
_IPV4_CIDR = re.compile(r"\b(?P<ip>\d{1,3}(?:\.\d{1,3}){3})/(?P<prefix>\d{1,2})\b")

# `Chain FORWARD (policy DROP 32 packets, 2688 bytes)`
# iptables abbreviates counters once they grow: `318K`, `2.5M`, `1G`.
# Demanding \d+ here silently dropped whichever rules were BUSIEST -
# the ones carrying real traffic - out of the parsed evidence, leaving
# a policy that looked more restrictive than the one being enforced.
_COUNT = r"\d+(?:\.\d+)?[KMGTP]?"
_SCALE = {"K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15}

_CHAIN = re.compile(
    r"^Chain\s+(?P<chain>\S+)\s+\(policy\s+(?P<policy>\S+)"
    r"(?:\s+(?P<packets>" + _COUNT + r")\s+packets,\s+"
    r"(?P<bytes>" + _COUNT + r")\s+bytes)?\)"
)
# `2      206 31300 ACCEPT     all  --  eth2   eth1    0.0.0.0/0   0.0.0.0/0`
_RULE = re.compile(
    r"^\s*(?P<num>\d+)\s+(?P<pkts>" + _COUNT + r")\s+"
    r"(?P<bytes>" + _COUNT + r")\s+(?P<target>\S+)\s+"
    r"(?P<proto>\S+)\s+\S+\s+(?P<in>\S+)\s+(?P<out>\S+)\s+"
    r"(?P<source>\S+)\s+(?P<destination>\S+)\s*(?P<extra>.*)$"
)


def _counter(value: str | None) -> int:
    """An iptables counter as a number, abbreviations expanded.

    Reported as observed, never judged: an approximate count is what
    the device offered, and rounding it back out is not an inference
    about the traffic, only about the notation.
    """

    text = (value or "").strip()
    if not text:
        return 0
    scale = _SCALE.get(text[-1].upper())
    if scale is None:
        try:
            return int(text)
        except ValueError:
            return 0
    try:
        return int(float(text[:-1]) * scale)
    except ValueError:
        return 0


class AtlasLabFirewallAdapter(DiscoveryAdapter):
    """Parse-only normalization of the AtlasLab firewall CLI."""

    vendor = "atlaslab"
    platform_family = "atlaslab-firewall"
    required_commands = (SHOW_VERSION, SHOW_INTERFACES)
    optional_commands = (
        SHOW_ROUTE, SHOW_FIREWALL_RULES, SHOW_RUNNING, SHOW_LLDP, SHOW_LOG,
    )

    def parse_inventory(
        self,
        raw_outputs: Mapping[str, str],
        management_ip_hint: str | None = None,
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        identity = _IDENTITY.search(version_text)
        if identity is None:
            raise DiscoveryParseError(
                "device identity could not be established: "
                f"{SHOW_VERSION!r} did not report an AtlasLab firewall identity",
                adapter=ADAPTER_NAME,
                command=SHOW_VERSION,
                field="hostname",
            )
        hostname = identity.group("hostname").strip()

        warnings: list[str] = []
        management_ip = self._management_ip(
            raw_outputs.get(SHOW_INTERFACES, ""), management_ip_hint
        )
        if management_ip is None and _valid_ip(management_ip_hint):
            management_ip = str(management_ip_hint).strip()
            warnings.append(
                f"management IP was not parsed from '{SHOW_INTERFACES}'; "
                "using the connection address as a deterministic fallback"
            )
        if management_ip is None:
            raise DiscoveryParseError(
                "device identity could not be established: no management IP "
                "was parsed and no connection address was supplied",
                adapter=ADAPTER_NAME,
                command=SHOW_INTERFACES,
                field="management_ip",
            )

        pretty = _PRETTY_NAME.search(version_text)
        os_name, os_version = _split_os(pretty.group("name") if pretty else "")
        metadata: dict[str, object] = {
            "kernel": identity.group("os").strip() or UNKNOWN,
            # The role is asserted by the platform itself, not inferred from a
            # hostname that happens to contain "fw".
            "device_role": "firewall",
        }
        if warnings:
            metadata["warnings"] = tuple(warnings)

        return NetworkDevice(
            device_id=f"atlaslab-fw:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform="AtlasLab firewall",
            os_name=os_name,
            os_version=os_version,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces: list[NetworkInterface] = []
        for line in (raw_outputs.get(SHOW_INTERFACES, "") or "").splitlines():
            parsed = _parse_interface_line(line)
            if parsed is not None:
                interfaces.append(parsed)
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        """LLDP adjacency only — never the routing table.

        The firewall runs no routing protocol, but the lab images grew lldpd,
        so each of its two legs now carries the peer naming itself. Deriving
        neighbors from `show route` would still be inventing adjacencies the
        device never claimed; LLDP is the device on the far end claiming one.
        """

        text = raw_outputs.get(SHOW_LLDP, "")
        if not text.strip():
            return ()
        return parse_lldp_neighbors(
            text, local_device_id=self._safe_local_device_id(raw_outputs)
        )

    def _safe_local_device_id(self, raw_outputs: Mapping[str, str]) -> str:
        identity = _IDENTITY.search(raw_outputs.get(SHOW_VERSION, ""))
        if identity is not None:
            return f"atlaslab-fw:{identity.group('hostname').strip()}"
        return "atlaslab-fw:unknown"

    def _management_ip(self, text: str, hint: str | None) -> str | None:
        """The address Atlas is actually managing this device on.

        Prefer the interface carrying the address we connected to: a firewall
        has several addressed legs, and picking "the first one" would name the
        device after an inside or outside interface depending on parse order.
        """

        addresses: list[str] = []
        for line in (text or "").splitlines():
            parsed = _parse_interface_line(line)
            if parsed is None or parsed.ip_address is None:
                continue
            if parsed.name == "lo":
                continue
            if hint and parsed.ip_address == str(hint).strip():
                return parsed.ip_address
            addresses.append(parsed.ip_address)
        return addresses[0] if addresses else None


class AtlasLabFirewallDriver(PlatformDriver):
    """AtlasLab perimeter firewall (Alpine + iptables, AtlasLab CLI)."""

    platform_id = "atlaslab-firewall"
    display_name = "AtlasLab firewall"
    vendor = "atlaslab"
    probe_command = SHOW_VERSION

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(re.search(r"\bAtlasLab firewall\b", probe_output or ""))

    @property
    def adapter(self) -> AtlasLabFirewallAdapter:
        return AtlasLabFirewallAdapter()

    def collection_plan(self) -> tuple[CapabilitySpec, ...]:
        return (
            CapabilitySpec("identity", SHOW_VERSION, required=True),
            CapabilitySpec("interfaces", SHOW_INTERFACES, required=True),
            CapabilitySpec("routes", SHOW_ROUTE),
            CapabilitySpec("firewall-rules", SHOW_FIREWALL_RULES),
            CapabilitySpec("lldp-neighbors", SHOW_LLDP),
            CapabilitySpec("configuration", SHOW_RUNNING),
        )

    def classify_output(self, spec: CapabilitySpec, output: str) -> CapabilityStatus:
        """This CLI reports an unknown command in the shell's words.

        The base class looks for IOS/vtysh markers ("% Unknown command"), which
        this platform never emits; without this it would read a shell error as
        successfully collected evidence.
        """

        stripped = (output or "").strip()
        folded = stripped.casefold()
        if "not found" in folded or folded.startswith("unknown command"):
            return CapabilityStatus(
                spec.name, "unavailable", "command not supported"
            )
        return super().classify_output(spec, output)

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        """Summarize the enforced policy into canonical metadata.

        This is what makes the firewall's picture its own: not interfaces and
        routes (every router has those) but *what it enforces*. Downstream
        consumers read `firewall` from metadata and never learn that iptables
        produced it.
        """

        raw = discovery.raw_outputs
        firewall = parse_firewall_rules(raw.get(SHOW_FIREWALL_RULES, ""))
        # The RIB is captured whether or not the rule set parsed: a firewall
        # that reports its routes but whose chain could not be read is still
        # a device whose forwarding we can reason about, and the two pieces
        # of evidence do not depend on each other.
        routing_table = iproute2_route_dicts(raw.get(SHOW_ROUTE, ""))
        # Policy rules come from the CONFIGURATION, not a live command.
        # This appliance CLI answers a fixed list and rejects everything
        # else, so there is no `ip rule` to ask for — but the config it
        # booted with is already captured, and the rules written there are
        # what the box is running. Reading them is evidence; inventing a
        # command the device would refuse is not.
        policy_captured = SHOW_RUNNING in raw
        policy_routes = ()
        if policy_captured:
            policy_routes = policy_route_dicts(parse_iproute2_rule_commands(
                raw.get(SHOW_RUNNING, ""), source_command=SHOW_RUNNING,
            ))
        if not firewall and not routing_table and not policy_captured:
            return discovery
        metadata = dict(discovery.result.device.metadata)
        if firewall:
            metadata["firewall"] = firewall
        if routing_table:
            metadata["route_count"] = _count_routes(raw.get(SHOW_ROUTE, ""))
            metadata["routing_table"] = routing_table
        if policy_captured:
            metadata["policy_routes"] = policy_routes
            metadata["policy_routes_captured"] = True
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
        )
        return replace(discovery, result=result)


def parse_firewall_rules(text: str) -> dict[str, object] | None:
    """The enforced FORWARD policy and its rules, as canonical facts.

    Counters are read as observed and never interpreted here: "0 packets" is
    reported, not judged. A rule that has never matched may be dead, or may be
    a correctly-configured deny that nothing has tried to violate — Atlas
    cannot tell the difference from this evidence, so it does not try.
    """

    lines = (text or "").splitlines()
    if not lines:
        return None
    chain = None
    for line in lines:
        chain = _CHAIN.match(line.strip())
        if chain:
            break
    if chain is None:
        return None

    rules: list[dict[str, object]] = []
    for line in lines:
        rule = _RULE.match(line)
        if rule is None:
            continue
        extra = (rule.group("extra") or "").strip()
        rules.append({
            "number": int(rule.group("num")),
            "target": rule.group("target"),
            "protocol": rule.group("proto"),
            "in_interface": _iface_or_any(rule.group("in")),
            "out_interface": _iface_or_any(rule.group("out")),
            "source": rule.group("source"),
            "destination": rule.group("destination"),
            "packets": _counter(rule.group("pkts")),
            "bytes": _counter(rule.group("bytes")),
            "detail": extra or None,
        })

    targets: dict[str, int] = {}
    for rule in rules:
        target = str(rule["target"])
        targets[target] = targets.get(target, 0) + 1

    return {
        "chain": chain.group("chain"),
        "default_policy": chain.group("policy"),
        "default_policy_packets": _counter(chain.group("packets")),
        "default_policy_bytes": _counter(chain.group("bytes")),
        "rule_count": len(rules),
        "rules_by_target": targets,
        "rules": tuple(
            tuple(sorted(rule.items(), key=lambda kv: kv[0])) for rule in rules
        ),
    }


def _iface_or_any(value: str) -> str | None:
    """iptables writes `*` for "any interface"; Atlas says so in words."""

    return None if value == "*" else value


def _parse_interface_line(line: str) -> NetworkInterface | None:
    match = _INTERFACE.match((line or "").rstrip())
    if match is None:
        return None
    name = match.group("name")
    if name.endswith(":") or not name:
        return None
    state = match.group("state").strip().casefold()
    if state not in {"up", "down", "unknown", "lower_up"}:
        return None
    addresses = match.group("addresses") or ""
    ipv4 = _IPV4_CIDR.search(addresses)
    metadata: dict[str, object] = {}
    if ipv4:
        metadata["prefix_length"] = int(ipv4.group("prefix"))
    return NetworkInterface(
        name=name,
        ip_address=ipv4.group("ip") if ipv4 else None,
        # `ip -br addr` reports one state; Atlas does not have separate line and
        # protocol status here, so protocol_status stays unset rather than
        # duplicating a value the device only stated once.
        status=state,
        metadata=metadata,
    )


def _count_routes(text: str) -> int:
    return len([line for line in (text or "").splitlines() if line.strip()])


def _split_os(pretty: str) -> tuple[str, str]:
    """`Alpine Linux v3.24` -> ("Alpine Linux", "v3.24")."""

    parts = (pretty or "").strip().rsplit(" ", 1)
    if len(parts) == 2 and parts[1]:
        return parts[0], parts[1]
    return (pretty or UNKNOWN), UNKNOWN


def _valid_ip(value: str | None) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
