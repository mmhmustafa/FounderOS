"""ACL policy evidence for path investigations (packet trace Phase 2).

Parses IOS/IOS-XE access-lists — numbered and named, standard and
extended — plus their ``ip access-group`` interface bindings, into
provenance-bearing records the path engine can evaluate a declared
packet intent (protocol/port, optionally a source address) against.

Rules of evidence, matching the rest of Atlas:

- An ACL line is **configured intent**, not an observed drop. Every
  record carries ``evidence_state: "configured"`` and cites the exact
  config file line it came from.
- Matching is three-valued: ``match`` / ``no-match`` / ``indeterminate``.
  A rule whose addresses (or qualifiers like ``established``) cannot be
  evaluated from the declared intent is *indeterminate* — the verdict
  says "this rule may apply", never a guessed permit or deny.
- First match wins; a fully-parsed ACL that matches nothing ends in the
  platform's implicit deny — reported as such, cited to the ACL itself.
- A bound ACL whose rules could not be parsed yields ``unparsed`` —
  "policy present, rules not parsed" — never silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network
from pathlib import Path
import re
from typing import Any


MATCH = "match"
NO_MATCH = "no-match"
INDETERMINATE = "indeterminate"

# Common IOS service-name → port translations (config keywords).
_SERVICE_PORTS = {
    "ftp-data": 20, "ftp": 21, "ssh": 22, "telnet": 23, "smtp": 25,
    "domain": 53, "bootps": 67, "bootpc": 68, "tftp": 69, "www": 80,
    "http": 80, "pop3": 110, "ntp": 123, "snmp": 161, "snmptrap": 162,
    "bgp": 179, "https": 443, "syslog": 514, "isakmp": 500, "rip": 520,
    "lpd": 515, "nntp": 119, "pim-auto-rp": 496, "exec": 512,
    "login": 513, "domain-s": 853,
}

_PROTOCOLS = {
    "ip", "tcp", "udp", "icmp", "igmp", "gre", "esp", "ahp", "ospf",
    "eigrp", "pim", "sctp",
}

# Interface-name canonicalization so a binding on "Gi0/1" matches the
# snapshot's "GigabitEthernet0/1". Keys and values are lowercase.
_INTERFACE_PREFIXES = {
    "fa": "fastethernet",
    "gi": "gigabitethernet",
    "ge": "gigabitethernet",
    "te": "tengigabitethernet",
    "twe": "twentyfivegigabitethernet",
    "fo": "fortygigabitethernet",
    "hu": "hundredgigabitethernet",
    "et": "ethernet",
    "eth": "ethernet",
    "po": "port-channel",
    "lo": "loopback",
    "vl": "vlan",
    "tu": "tunnel",
    "se": "serial",
    "ma": "management",
    "mgmt": "management",
}

_NAME_SPLIT = re.compile(r"^([a-z\-]+)\s*(.*)$")


def canonical_interface(name: str) -> str:
    """Lowercased, abbreviation-expanded interface identity."""

    folded = name.strip().casefold().replace(" ", "")
    match = _NAME_SPLIT.match(folded)
    if not match:
        return folded
    alpha, rest = match.group(1), match.group(2)
    expanded = _INTERFACE_PREFIXES.get(alpha, alpha)
    for full in _INTERFACE_PREFIXES.values():
        if alpha == full:
            expanded = full
            break
    return expanded + rest


@dataclass(frozen=True)
class PortMatch:
    """One port constraint (``eq 443``, ``range 8000 8100``…)."""

    op: str                       # eq | neq | gt | lt | range
    values: tuple[int, ...]       # resolved numbers; empty if unresolvable
    raw: str = ""

    def matches(self, port: int) -> str:
        if not self.values:
            return INDETERMINATE
        if self.op == "eq":
            return MATCH if port in self.values else NO_MATCH
        if self.op == "neq":
            return MATCH if port not in self.values else NO_MATCH
        if self.op == "gt":
            return MATCH if port > self.values[0] else NO_MATCH
        if self.op == "lt":
            return MATCH if port < self.values[0] else NO_MATCH
        if self.op == "range" and len(self.values) == 2:
            low, high = self.values
            return MATCH if low <= port <= high else NO_MATCH
        return INDETERMINATE

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "values": list(self.values), "raw": self.raw}


@dataclass(frozen=True)
class AclRule:
    """One access-list entry, cited to its configuration line."""

    acl: str
    action: str                   # permit | deny
    protocol: str                 # ip | tcp | udp | icmp | ...
    source: str                   # any | host A.B.C.D | A.B.C.D W.W.W.W | raw
    destination: str
    line_number: int              # 1-based line in the captured config
    sequence: int | None = None
    source_port: PortMatch | None = None
    destination_port: PortMatch | None = None
    qualifiers: tuple[str, ...] = ()   # established, echo, log, dscp…
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "acl": self.acl,
            "action": self.action,
            "protocol": self.protocol,
            "source": self.source,
            "destination": self.destination,
            "line_number": self.line_number,
            "sequence": self.sequence,
            "source_port": self.source_port.to_dict()
            if self.source_port else None,
            "destination_port": self.destination_port.to_dict()
            if self.destination_port else None,
            "qualifiers": list(self.qualifiers),
            "raw": self.raw,
            "evidence_state": "configured",
        }

    def cite(self, source_path: str) -> str:
        where = f"{source_path}:{self.line_number}" if source_path else \
            f"line {self.line_number}"
        return f"ACL {self.acl} ({where}): {self.raw}"


@dataclass(frozen=True)
class AclBinding:
    """``ip access-group NAME in|out`` on an interface."""

    interface: str
    direction: str                # in | out
    acl: str
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "direction": self.direction,
            "acl": self.acl,
            "line_number": self.line_number,
            "evidence_state": "configured",
        }


@dataclass(frozen=True)
class DevicePolicy:
    """Everything policy-shaped one captured config declares."""

    hostname: str
    source_path: str
    rules: dict[str, tuple[AclRule, ...]] = field(default_factory=dict)
    bindings: tuple[AclBinding, ...] = ()
    unparsed_acls: tuple[str, ...] = ()   # named/bound but rules unreadable

    def bindings_for(self, interface: str, direction: str) -> tuple[AclBinding, ...]:
        wanted = canonical_interface(interface)
        return tuple(
            binding for binding in self.bindings
            if binding.direction == direction
            and canonical_interface(binding.interface) == wanted
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "source_path": self.source_path,
            "rules": {
                name: [rule.to_dict() for rule in rules]
                for name, rules in self.rules.items()
            },
            "bindings": [binding.to_dict() for binding in self.bindings],
            "unparsed_acls": list(self.unparsed_acls),
        }


@dataclass(frozen=True)
class PolicyVerdict:
    """The outcome of evaluating one bound ACL against declared intent."""

    kind: str                     # permit | deny | implicit-deny | indeterminate | unparsed
    binding: AclBinding
    rule: AclRule | None = None


# -- parsing ---------------------------------------------------------------------


_NUMBERED = re.compile(
    r"^access-list\s+(\d+)\s+(permit|deny)\s+(.*)$", re.IGNORECASE
)
_NAMED_HEADER = re.compile(
    r"^ip\s+access-list\s+(standard|extended)\s+(\S+)\s*$", re.IGNORECASE
)
_NAMED_RULE = re.compile(
    r"^\s+(?:(\d+)\s+)?(permit|deny)\s+(.*)$", re.IGNORECASE
)
_INTERFACE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_ACCESS_GROUP = re.compile(
    r"^\s+ip\s+access-group\s+(\S+)\s+(in|out)\s*$", re.IGNORECASE
)
_REMARK = re.compile(r"^\s*(?:\d+\s+)?remark\b", re.IGNORECASE)


def parse_device_policy(
    text: str, *, hostname: str, source_path: str = ""
) -> DevicePolicy:
    """Parse one captured running configuration into policy evidence."""

    rules: dict[str, list[AclRule]] = {}
    unparsed: list[str] = []
    bindings: list[AclBinding] = []
    named_acl: tuple[str, bool] | None = None   # (name, is_extended)
    interface: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("!"):
            named_acl = named_acl if line.strip() != "!" else None
            interface = interface if line.strip() != "!" else None
            continue
        if _REMARK.match(line):
            continue

        header = _NAMED_HEADER.match(line)
        if header:
            named_acl = (header.group(2), header.group(1).lower() == "extended")
            interface = None
            rules.setdefault(named_acl[0], [])
            continue

        iface = _INTERFACE.match(line)
        if iface:
            interface = iface.group(1)
            named_acl = None
            continue

        if not line.startswith((" ", "\t")):
            # Any other top-level command ends an indented block.
            named_acl = None
            interface = None

        numbered = _NUMBERED.match(line)
        if numbered:
            number, action, body = numbered.groups()
            extended = 100 <= int(number) <= 199 or 2000 <= int(number) <= 2699
            rule = _parse_rule_body(
                acl=number, action=action.lower(), body=body,
                line_number=line_number, sequence=None, extended=extended,
                raw=line.strip(),
            )
            if rule is None:
                if number not in unparsed:
                    unparsed.append(number)
            else:
                rules.setdefault(number, []).append(rule)
            continue

        if named_acl is not None:
            entry = _NAMED_RULE.match(line)
            if entry:
                sequence, action, body = entry.groups()
                name, extended = named_acl
                rule = _parse_rule_body(
                    acl=name, action=action.lower(), body=body,
                    line_number=line_number,
                    sequence=int(sequence) if sequence else None,
                    extended=extended, raw=line.strip(),
                )
                if rule is None:
                    if name not in unparsed:
                        unparsed.append(name)
                else:
                    rules.setdefault(name, []).append(rule)
                continue

        if interface is not None:
            group = _ACCESS_GROUP.match(line)
            if group:
                bindings.append(
                    AclBinding(
                        interface=interface,
                        direction=group.group(2).lower(),
                        acl=group.group(1),
                        line_number=line_number,
                    )
                )

    ordered = {
        name: tuple(
            sorted(items, key=lambda rule: (
                rule.sequence if rule.sequence is not None else 0,
            ))
            if all(item.sequence is not None for item in items) else items
        )
        for name, items in rules.items()
    }
    return DevicePolicy(
        hostname=hostname,
        source_path=source_path,
        rules=ordered,
        bindings=tuple(bindings),
        unparsed_acls=tuple(unparsed),
    )


def load_device_policies(
    roots: tuple[Path, ...],
    hostnames: tuple[str, ...],
    *,
    safe_name,
) -> dict[str, DevicePolicy]:
    """Parse each hostname's captured config found under any root.

    ``roots`` are scope output directories (each holding ``configs/``);
    the first root containing a device's config wins, mirroring how
    captured-config citation already resolves across scopes.
    """

    policies: dict[str, DevicePolicy] = {}
    for hostname in hostnames:
        for root in roots:
            config = (
                Path(root) / "configs" / safe_name(hostname)
                / "running_config.txt"
            )
            if not config.is_file():
                continue
            try:
                text = config.read_text(encoding="utf-8")
            except OSError:
                continue
            policies[hostname.casefold()] = parse_device_policy(
                text,
                hostname=hostname,
                source_path=f"configs/{safe_name(hostname)}/running_config.txt",
            )
            break
    return policies


def _parse_rule_body(
    *,
    acl: str,
    action: str,
    body: str,
    line_number: int,
    sequence: int | None,
    extended: bool,
    raw: str,
) -> AclRule | None:
    tokens = body.split()
    if not tokens:
        return None
    try:
        if not extended:
            # Standard ACL: source only, protocol is implicitly "ip".
            source, tokens = _parse_endpoint(tokens)
            return AclRule(
                acl=acl, action=action, protocol="ip", source=source,
                destination="any", line_number=line_number,
                sequence=sequence, qualifiers=tuple(tokens), raw=raw,
            )
        protocol = tokens.pop(0).lower()
        if protocol not in _PROTOCOLS:
            return None
        source, tokens = _parse_endpoint(tokens)
        source_port, tokens = _parse_port(tokens)
        destination, tokens = _parse_endpoint(tokens)
        destination_port, tokens = _parse_port(tokens)
        return AclRule(
            acl=acl, action=action, protocol=protocol, source=source,
            destination=destination, line_number=line_number,
            sequence=sequence, source_port=source_port,
            destination_port=destination_port,
            qualifiers=tuple(token.lower() for token in tokens), raw=raw,
        )
    except (IndexError, ValueError):
        return None


def _parse_endpoint(tokens: list[str]) -> tuple[str, list[str]]:
    head = tokens[0].lower()
    if head == "any":
        return "any", tokens[1:]
    if head == "host":
        ip_address(tokens[1])
        return f"host {tokens[1]}", tokens[2:]
    if head in ("object-group", "addrgroup"):
        return f"{head} {tokens[1]}", tokens[2:]
    # A.B.C.D WILDCARD
    ip_address(tokens[0])
    ip_address(tokens[1])
    return f"{tokens[0]} {tokens[1]}", tokens[2:]


def _parse_port(tokens: list[str]) -> tuple[PortMatch | None, list[str]]:
    if not tokens:
        return None, tokens
    op = tokens[0].lower()
    if op not in ("eq", "neq", "gt", "lt", "range"):
        return None, tokens
    count = 2 if op == "range" else 1
    names = tokens[1:1 + count]
    values: list[int] = []
    for name in names:
        if name.isdigit():
            values.append(int(name))
        elif name.lower() in _SERVICE_PORTS:
            values.append(_SERVICE_PORTS[name.lower()])
        else:
            values = []
            break
    return (
        PortMatch(op=op, values=tuple(values), raw=" ".join([op, *names])),
        tokens[1 + count:],
    )


# -- matching --------------------------------------------------------------------


def match_rule(rule: AclRule, intent: dict) -> str:
    """Three-valued match of one rule against declared intent.

    ``intent`` keys used: ``protocol`` (tcp/udp/icmp), ``port``,
    ``source_address``. Anything the intent does not declare and the
    rule constrains is *indeterminate*, never assumed.
    """

    verdicts = [
        _match_protocol(rule.protocol, str(intent.get("protocol") or "")),
        _match_address(rule.source, str(intent.get("source_address") or "")),
        _match_address(rule.destination, ""),
        INDETERMINATE if rule.source_port is not None else MATCH,
        _match_destination_port(rule, intent),
    ]
    if any(item == NO_MATCH for item in verdicts):
        return NO_MATCH
    # Qualifiers Atlas does not model (established, icmp types, dscp…)
    # narrow the rule in ways declared intent cannot settle.
    meaningful = [
        token for token in rule.qualifiers
        if token not in ("log", "log-input")
    ]
    if meaningful:
        return INDETERMINATE
    if any(item == INDETERMINATE for item in verdicts):
        return INDETERMINATE
    return MATCH


def evaluate_acl(rules: tuple[AclRule, ...], intent: dict) -> tuple[str, AclRule | None]:
    """First-match walk ending in the implicit deny.

    Returns ``(kind, rule)`` where kind is ``permit``/``deny`` (definite,
    from ``rule``), ``implicit-deny`` (no rule matched, all definite), or
    ``indeterminate`` (the first rule whose applicability cannot be
    decided — the walk cannot honestly continue past it).
    """

    for rule in rules:
        verdict = match_rule(rule, intent)
        if verdict == MATCH:
            return rule.action, rule
        if verdict == INDETERMINATE:
            return INDETERMINATE, rule
    return "implicit-deny", None


def evaluate_bindings(
    policy: DevicePolicy,
    intent: dict,
    checkpoints: tuple[tuple[str, str], ...],
) -> tuple[PolicyVerdict, ...]:
    """Evaluate every ACL bound at the given (interface, direction) pairs."""

    verdicts: list[PolicyVerdict] = []
    for interface, direction in checkpoints:
        if not interface:
            continue
        for binding in policy.bindings_for(interface, direction):
            rules = policy.rules.get(binding.acl, ())
            if not rules or binding.acl in policy.unparsed_acls:
                verdicts.append(PolicyVerdict(kind="unparsed", binding=binding))
                continue
            kind, rule = evaluate_acl(rules, intent)
            verdicts.append(PolicyVerdict(kind=kind, binding=binding, rule=rule))
    return tuple(verdicts)


def _match_protocol(rule_protocol: str, intent_protocol: str) -> str:
    if rule_protocol == "ip":
        return MATCH
    if not intent_protocol:
        return INDETERMINATE
    return MATCH if rule_protocol == intent_protocol.casefold() else NO_MATCH


def _match_address(spec: str, known: str) -> str:
    if spec == "any":
        return MATCH
    if not known:
        return INDETERMINATE
    try:
        address = ip_address(known)
        if spec.startswith("host "):
            return MATCH if str(address) == spec.split()[1] else NO_MATCH
        parts = spec.split()
        if len(parts) == 2:
            base, wildcard = parts
            hostmask_network = ip_network(f"{base}/{wildcard}", strict=False)
            return MATCH if address in hostmask_network else NO_MATCH
    except ValueError:
        return INDETERMINATE
    return INDETERMINATE


def _match_destination_port(rule: AclRule, intent: dict) -> str:
    if rule.destination_port is None:
        return MATCH
    port_raw = str(intent.get("port") or "")
    if not port_raw.isdigit():
        return INDETERMINATE
    return rule.destination_port.matches(int(port_raw))
