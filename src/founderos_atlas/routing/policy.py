"""Policy-based routing, as canonical, platform-neutral facts.

The RIB answers "where does this PREFIX go". Policy routing answers a
different question — "where does THIS FLOW go" — and it answers first,
overriding the routing table for traffic it matches. A path verdict built
only on longest-prefix match is therefore not merely incomplete on a
device with PBR; it can be confidently wrong, sending a flow down the
route the RIB would pick while the device sends it somewhere else.

Every platform expresses this differently and none of them agree:

  FortiOS   ``config router policy`` — numbered entries with input-device,
            src/dst, protocol, port range, gateway and output-device.
  Linux     ``ip rule`` — a priority-ordered list selecting a routing
            TABLE, whose routes then decide the next hop.
  IOS-like  ``route-map`` clauses (match/set) bound to an INGRESS
            interface by ``ip policy route-map``. The binding is half the
            fact: a route-map nothing references forwards nothing.

They normalise into one `PolicyRoute`, so the engine asks a single
question of every platform, and a device Atlas cannot read policy from is
distinguishable from one that has none — silence is not evidence of
absence, and the two must never look alike.

Nothing here is inferred. An entry whose match Atlas cannot read keeps
None for that field, which means "not constrained" only where the
platform itself means that; where a rule cannot be understood at all it is
skipped rather than guessed into something plausible.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import re


@dataclass(frozen=True)
class PolicyRoute:
    """One policy rule, from any platform.

    Every match field is optional and None means UNCONSTRAINED — the rule
    does not care about that property. This mirrors how the devices
    themselves treat an omitted match clause, so an absent field never has
    to be guessed at evaluation time.
    """

    sequence: int
    source: str | None = None
    destination: str | None = None
    protocol: str | None = None
    destination_ports: tuple[int, ...] = ()
    ingress_interface: str | None = None
    next_hop: str | None = None
    egress_interface: str | None = None
    table: str | None = None
    disabled: bool = False
    name: str | None = None
    source_command: str | None = None
    # Match clauses Atlas read but cannot RESOLVE — a route-map matching a
    # prefix-list by name, whose contents were never captured. This is the
    # difference between "this rule constrains nothing" and "this rule
    # constrains something Atlas cannot see", and collapsing the second
    # into the first would make the rule appear to match every flow.
    unresolved_matches: tuple[str, ...] = ()

    def directs_traffic(self) -> bool:
        """Whether this rule actually sends traffic somewhere.

        A rule can match and still not redirect — Linux rules that select
        a table, and IOS route-map clauses with no ``set ip next-hop``,
        both leave forwarding to the RIB. Those still MATTER (they stop
        later rules being consulted), so they are kept, but they must not
        be reported as a next hop the device never named.
        """

        return bool(self.next_hop or self.egress_interface)

    def matches(
        self,
        *,
        source_address: str | None = None,
        destination_address: str | None = None,
        protocol: str | None = None,
        destination_port: int | None = None,
        ingress_interface: str | None = None,
    ) -> bool | None:
        """Three-valued: True, False, or None for "cannot tell".

        None is the important one. If a rule constrains a property the
        caller did not declare — a source prefix when the trace never said
        which address it starts from — then whether it applies is UNKNOWN,
        and an unknown must not be rounded to "no". Reporting a flow as
        following the RIB when an unread policy rule might divert it is
        exactly the false confidence this module exists to prevent.
        """

        if self.disabled:
            return False
        # A criterion Atlas could not resolve keeps the rule permanently
        # undecidable: it can be ruled OUT by a contradiction below, but it
        # can never be confirmed, because confirming it would assert that
        # an unseen prefix-list contains this flow.
        undetermined = bool(self.unresolved_matches)

        for rule_value, declared in (
            (self.source, source_address),
            (self.destination, destination_address),
        ):
            if rule_value is None:
                continue
            if declared is None:
                undetermined = True
                continue
            if not _address_in(declared, rule_value):
                return False

        if self.protocol is not None:
            if protocol is None:
                undetermined = True
            elif protocol.lower() != self.protocol.lower():
                return False

        if self.destination_ports:
            if destination_port is None:
                undetermined = True
            elif destination_port not in self.destination_ports:
                return False

        if self.ingress_interface is not None:
            if ingress_interface is None:
                undetermined = True
            elif not _same_interface(ingress_interface, self.ingress_interface):
                return False

        return None if undetermined else True

    def describe(self) -> str:
        criteria = []
        if self.ingress_interface:
            criteria.append(f"in {self.ingress_interface}")
        if self.source:
            criteria.append(f"from {self.source}")
        if self.destination:
            criteria.append(f"to {self.destination}")
        if self.protocol:
            proto = self.protocol.upper()
            if self.destination_ports:
                ports = ",".join(str(port) for port in self.destination_ports)
                proto = f"{proto}/{ports}"
            criteria.append(proto)
        for unresolved in self.unresolved_matches:
            # Named, not silently dropped: the reader has to know the rule
            # turns on something Atlas could not read.
            criteria.append(f"matching {unresolved} (contents not captured)")
        where = " ".join(criteria) if criteria else "any traffic"
        if self.next_hop:
            action = f"via {self.next_hop}"
            if self.egress_interface:
                action += f" on {self.egress_interface}"
        elif self.egress_interface:
            action = f"out {self.egress_interface}"
        elif self.table:
            action = f"looked up in table {self.table}"
        else:
            action = "left to the routing table"
        label = self.name or f"rule {self.sequence}"
        return f"{label}: {where} {action}"


def _address_in(address: str, prefix: str) -> bool:
    """Whether an address falls in a prefix, tolerating a bare address."""

    try:
        target = ip_address(address)
    except ValueError:
        return False
    try:
        network = ip_network(prefix, strict=False)
    except ValueError:
        try:
            return ip_address(prefix) == target
        except ValueError:
            return False
    return target in network


def _same_interface(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


def first_matching_policy(
    policies: tuple[PolicyRoute, ...] | list[PolicyRoute],
    **flow,
) -> tuple[PolicyRoute | None, tuple[PolicyRoute, ...]]:
    """The rule that decides this flow, plus the rules that MIGHT have.

    Rules are evaluated in sequence, first match wins — as every platform
    here does it. A rule that cannot be decided (see `matches`) does not
    win, but it does not vanish either: it is returned as undetermined so
    the caller can say "this device may divert the flow, and Atlas cannot
    tell from what it captured" instead of quietly falling through to the
    routing table.
    """

    undetermined: list[PolicyRoute] = []
    for policy in sorted(policies, key=lambda item: item.sequence):
        verdict = policy.matches(**flow)
        if verdict is True:
            return policy, tuple(undetermined)
        if verdict is None:
            undetermined.append(policy)
    return None, tuple(undetermined)


# -- FortiOS ---------------------------------------------------------------
# `config router policy` / `edit <n>` / `set ...` / `next`. Ports arrive as
# start/end pairs; a whole range is kept as the explicit set of ports so
# matching needs no range arithmetic at evaluation time.

_FORTI_EDIT = re.compile(r"^\s*edit\s+(\d+)\s*$", re.IGNORECASE)
_FORTI_SET = re.compile(r"^\s*set\s+(\S+)\s+(.*?)\s*$", re.IGNORECASE)
# A FortiOS port range is capped when expanded: an unconstrained "1-65535"
# is the platform saying "any port", and materialising 65k integers to
# express that would be absurd.
_FORTI_PORT_LIMIT = 4096


def parse_fortios_policy_routes(
    text: str, *, source_command: str = "show router policy"
) -> tuple[PolicyRoute, ...]:
    policies: list[PolicyRoute] = []
    current: dict[str, object] | None = None
    for raw in (text or "").splitlines():
        edit = _FORTI_EDIT.match(raw)
        if edit:
            current = {"sequence": int(edit.group(1))}
            continue
        if re.match(r"^\s*next\s*$", raw, re.IGNORECASE):
            if current:
                policies.append(_fortios_entry(current, source_command))
            current = None
            continue
        if current is None:
            continue
        setter = _FORTI_SET.match(raw)
        if not setter:
            continue
        key = setter.group(1).lower()
        value = setter.group(2).strip().strip('"')
        current[key] = value
    if current:
        policies.append(_fortios_entry(current, source_command))
    return tuple(policies)


def _fortios_entry(fields: dict, source_command: str) -> PolicyRoute:
    ports: tuple[int, ...] = ()
    start = _as_int(fields.get("start-port"))
    end = _as_int(fields.get("end-port"))
    if start is not None:
        stop = end if end is not None else start
        if 0 < stop - start < _FORTI_PORT_LIMIT:
            ports = tuple(range(start, stop + 1))
        elif stop == start:
            ports = (start,)
    protocol = _fortios_protocol(fields.get("protocol"))
    return PolicyRoute(
        sequence=int(fields["sequence"]),
        source=_clean_prefix(fields.get("src")),
        destination=_clean_prefix(fields.get("dst")),
        protocol=protocol,
        destination_ports=ports,
        ingress_interface=_clean(fields.get("input-device")),
        next_hop=_clean(fields.get("gateway")),
        egress_interface=_clean(fields.get("output-device")),
        # FortiOS spells "this entry is off" as status disable.
        disabled=str(fields.get("status", "")).lower() == "disable",
        source_command=source_command,
    )


# FortiOS records the IP protocol NUMBER. Only the ones a path question can
# actually declare are named; anything else keeps its number rather than
# being mapped to a plausible guess.
_IP_PROTOCOL_NUMBERS = {"1": "icmp", "6": "tcp", "17": "udp"}


def _fortios_protocol(value: object) -> str | None:
    text = _clean(value)
    if not text or text == "0":       # 0 is FortiOS for "any protocol"
        return None
    return _IP_PROTOCOL_NUMBERS.get(text, text)


# -- Linux / iproute2 ------------------------------------------------------
# `ip rule` lines: "<priority>:\tfrom <src> [to <dst>] [iif <dev>] lookup
# <table>". The rule selects a TABLE; the routes in it decide the next hop,
# so these carry `table` and no next_hop — saying otherwise would invent a
# gateway the rule never named.

_RULE_LINE = re.compile(r"^\s*(\d+):\s+(.*?)\s*$")


def parse_iproute2_rules(
    text: str, *, source_command: str = "ip rule"
) -> tuple[PolicyRoute, ...]:
    policies: list[PolicyRoute] = []
    for raw in (text or "").splitlines():
        match = _RULE_LINE.match(raw)
        if not match:
            continue
        priority = int(match.group(1))
        body = match.group(2)
        table = _token_after(body, "lookup") or _token_after(body, "table")
        if table is None:
            continue          # not a lookup rule (blackhole/prohibit): skip
        source = _token_after(body, "from")
        destination = _token_after(body, "to")
        policies.append(PolicyRoute(
            sequence=priority,
            # "from all" is iproute2 for unconstrained, NOT a prefix.
            source=None if source in (None, "all") else _clean_prefix(source),
            destination=(
                None if destination in (None, "all")
                else _clean_prefix(destination)
            ),
            ingress_interface=_token_after(body, "iif"),
            table=table,
            source_command=source_command,
        ))
    return tuple(policies)


_RULE_ADD = re.compile(r"(?:^|\s)ip\s+rule\s+add\s+(.*)$", re.IGNORECASE)


def parse_iproute2_rule_commands(
    text: str, *, source_command: str = "show running-config"
) -> tuple[PolicyRoute, ...]:
    """Policy rules as CONFIGURED, from `ip rule add` lines.

    A Linux firewall's configuration is a shell script, and some of them
    expose it where they expose no `ip rule` command at all — a fixed
    command allow-list is common on appliance CLIs. Reading the rules the
    device booted with is then the only evidence available, and it is real
    evidence: it is what the operator wrote and the box ran.

    The written form differs from the displayed one: `ip rule add from X
    lookup Y pref N` rather than `N:\tfrom X lookup Y`. A rule with no
    explicit preference gets the kernel's own default of 32766, so
    ordering stays meaningful instead of collapsing to zero.

    A `del` is NOT a rule and is skipped rather than read as one — the
    same line with one word changed means the opposite thing.
    """

    policies: list[PolicyRoute] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("#") or " rule del " in f" {line} ":
            continue
        match = _RULE_ADD.search(line)
        if not match:
            continue
        body = match.group(1).split("#", 1)[0].strip()
        table = _token_after(body, "lookup") or _token_after(body, "table")
        if table is None:
            continue
        preference = (
            _token_after(body, "pref")
            or _token_after(body, "preference")
            or _token_after(body, "priority")
        )
        source = _token_after(body, "from")
        destination = _token_after(body, "to")
        policies.append(PolicyRoute(
            sequence=_as_int(preference) if preference is not None else 32766,
            source=None if source in (None, "all") else _clean_prefix(source),
            destination=(
                None if destination in (None, "all")
                else _clean_prefix(destination)
            ),
            ingress_interface=_token_after(body, "iif"),
            table=table,
            source_command=source_command,
        ))
    return tuple(policies)


def _token_after(body: str, keyword: str) -> str | None:
    parts = body.split()
    for index, token in enumerate(parts):
        if token == keyword and index + 1 < len(parts):
            return parts[index + 1]
    return None


# -- IOS / NX-OS route-maps ------------------------------------------------
# Two halves, and BOTH are needed. `show route-map` gives the match/set
# clauses; `show ip policy` gives which interface each map is bound to. A
# route-map no interface references forwards nothing at all, so parsing
# only the first half would report policy routing on a device that has
# none configured in the path.

_RM_HEADER = re.compile(
    r"^route-map\s+(\S+),\s*(permit|deny),\s*sequence\s+(\d+)",
    re.IGNORECASE,
)
_RM_MATCH_IP = re.compile(
    r"^\s*ip address\s+(?:prefix-lists?|access-lists?)?:?\s*(.+?)\s*$",
    re.IGNORECASE,
)
_RM_SET_NEXT_HOP = re.compile(r"^\s*ip next-hop\s+(\S+)", re.IGNORECASE)
_RM_SET_INTERFACE = re.compile(r"^\s*interface\s+(\S+)", re.IGNORECASE)
_POLICY_BINDING = re.compile(
    r"^\s*(?:Interface\s+)?(\S+)\s+(?:route-map\s+)?(\S+)\s*$", re.IGNORECASE
)


def parse_ip_policy_bindings(
    text: str,
) -> dict[str, str]:
    """Interface -> route-map name, from `show ip policy`.

    The header line is skipped rather than parsed: its two columns are
    named, not valued, and treating it as data would bind a route-map
    called "Route map" to an interface called "Interface".
    """

    bindings: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        lowered = line.strip().lower()
        if lowered.startswith("interface") and "route" in lowered and (
            "map" in lowered
        ) and not re.search(r"route-map\s+\S", lowered):
            continue                      # column header, not a binding
        match = _POLICY_BINDING.match(line)
        if not match:
            continue
        interface, route_map = match.group(1), match.group(2)
        if interface.lower() == "interface":
            continue
        bindings[interface] = route_map
    return bindings


def parse_route_map_policy_routes(
    route_map_text: str,
    *,
    bindings: dict[str, str] | None = None,
    source_command: str = "show route-map",
) -> tuple[PolicyRoute, ...]:
    """Route-map clauses, joined to the interfaces that USE them.

    A clause is emitted once per interface bound to its map. Unbound maps
    yield nothing: they are configuration the device is not applying, and
    reporting them as policy routing would overstate what the device does.
    """

    by_interface: dict[str, list[str]] = {}
    for interface, route_map in (bindings or {}).items():
        by_interface.setdefault(route_map, []).append(interface)

    policies: list[PolicyRoute] = []
    name: str | None = None
    sequence = 0
    action = "permit"
    section: str | None = None
    next_hop: str | None = None
    egress: str | None = None
    unresolved: list[str] = []

    def flush() -> None:
        if name is None:
            return
        interfaces = by_interface.get(name) or []
        for interface in sorted(interfaces):
            policies.append(PolicyRoute(
                sequence=sequence,
                protocol=None,
                ingress_interface=interface,
                next_hop=next_hop,
                egress_interface=egress,
                # A deny clause in PBR means "do not policy-route this",
                # i.e. fall back to the RIB — not "drop".
                disabled=action.lower() == "deny",
                name=f"{name} seq {sequence}",
                unresolved_matches=tuple(unresolved),
                source_command=source_command,
            ))

    for raw in (route_map_text or "").splitlines():
        header = _RM_HEADER.match(raw.strip())
        if header:
            flush()
            name, action, sequence = (
                header.group(1), header.group(2), int(header.group(3))
            )
            section = None
            next_hop = None
            egress = None
            unresolved = []
            continue
        if name is None:
            continue
        stripped = raw.strip().lower()
        if stripped.startswith("match clauses"):
            section = "match"
            continue
        if stripped.startswith("set clauses"):
            section = "set"
            continue
        if stripped.startswith("policy routing matches"):
            section = None
            continue
        if section == "match":
            # The clause names a prefix-list or ACL whose CONTENTS Atlas
            # has not captured. Recorded as unresolved rather than
            # dropped: dropping it would leave a rule that appears to
            # constrain nothing, and so to divert every flow.
            criterion = _RM_MATCH_IP.match(raw)
            if criterion and criterion.group(1):
                unresolved.append("ip address " + criterion.group(1).strip())
            continue
        if section == "set":
            hop = _RM_SET_NEXT_HOP.match(raw)
            if hop:
                next_hop = hop.group(1)
                continue
            interface = _RM_SET_INTERFACE.match(raw)
            if interface:
                egress = interface.group(1)
    flush()
    return tuple(policies)


# -- Junos filter-based forwarding -----------------------------------------
# Junos has no route-map. It matches traffic with a firewall FILTER term and
# sends it to a routing INSTANCE: `then routing-instance <name>`. The
# clauses live in the configuration, not in `show firewall filter` — that
# command reports counters — so they are read from the set-format config the
# driver already captures.
#
# As with route-maps, the binding is half the fact: a filter applied to no
# interface forwards nothing, and the interface it is applied to is the
# ingress the rule matches on.

_JUNOS_TERM = re.compile(
    r"^set\s+firewall\s+family\s+inet\s+filter\s+(\S+)\s+term\s+(\S+)\s+"
    r"(from|then)\s+(.*)$",
    re.IGNORECASE,
)
_JUNOS_BINDING = re.compile(
    r"^set\s+interfaces\s+(\S+)\s+unit\s+(\S+)\s+family\s+inet\s+"
    r"filter\s+input\s+(\S+)\s*$",
    re.IGNORECASE,
)


def parse_junos_filter_forwarding(
    text: str, *, source_command: str = "show configuration | display set"
) -> tuple[PolicyRoute, ...]:
    terms: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    bindings: dict[str, list[str]] = {}

    for raw in (text or "").splitlines():
        line = raw.strip()
        binding = _JUNOS_BINDING.match(line)
        if binding:
            interface = f"{binding.group(1)}.{binding.group(2)}"
            bindings.setdefault(binding.group(3), []).append(interface)
            continue
        match = _JUNOS_TERM.match(line)
        if not match:
            continue
        key = (match.group(1), match.group(2))
        if key not in terms:
            terms[key] = {}
            order.append(key)
        clause = match.group(3).lower()
        body = match.group(4).strip()
        parts = body.split()
        if not parts:
            continue
        name, value = parts[0].lower(), " ".join(parts[1:]).strip()
        if clause == "from":
            terms[key].setdefault("from", {})[name] = value
        else:
            terms[key].setdefault("then", {})[name] = value

    policies: list[PolicyRoute] = []
    for index, key in enumerate(order):
        filter_name, term_name = key
        fields = terms[key]
        instance = (fields.get("then") or {}).get("routing-instance")
        if not instance:
            # A term that does not redirect is not policy routing. Accept,
            # discard and counter-only terms belong to the firewall model,
            # not this one.
            continue
        criteria = fields.get("from") or {}
        port = _as_int(criteria.get("destination-port"))
        interfaces = bindings.get(filter_name) or []
        for interface in sorted(interfaces):
            policies.append(PolicyRoute(
                sequence=index,
                source=_clean_prefix(criteria.get("source-address")),
                destination=_clean_prefix(criteria.get("destination-address")),
                protocol=_clean(criteria.get("protocol")),
                destination_ports=(port,) if port is not None else (),
                ingress_interface=interface,
                # The instance names a routing TABLE. Its routes choose the
                # next hop, so none is claimed here.
                table=instance,
                name=f"{filter_name} term {term_name}",
                source_command=source_command,
            ))
    return tuple(policies)


# -- PAN-OS policy-based forwarding ----------------------------------------
# `show running pbf-policy` prints the same vsys/rule block shape as the
# security policy this driver already reads: `name {` then `key value;`
# lines. PBF matches on a source ZONE rather than an interface, which is
# not the same thing — see below.

_PANOS_RULE = re.compile(r"^\s*([A-Za-z0-9_.:\-]+)\s*\{\s*$")
_PANOS_FIELD = re.compile(r"^\s*([A-Za-z0-9/_\-]+)[:\s]\s*(.+?);?\s*$")


def parse_panos_pbf_rules(
    text: str, *, source_command: str = "show running pbf-policy"
) -> tuple[PolicyRoute, ...]:
    policies: list[PolicyRoute] = []
    current: dict[str, str] | None = None
    name: str | None = None
    depth = 0
    sequence = 0

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        opened = _PANOS_RULE.match(line)
        if opened:
            depth += 1
            # Depth 1 is the vsys wrapper; a rule is the block inside it.
            if depth >= 2:
                name = opened.group(1)
                current = {}
            continue
        if stripped.startswith("}"):
            if current is not None and name is not None:
                policies.append(_panos_entry(
                    name, current, sequence, source_command
                ))
                sequence += 1
            current = None
            name = None
            depth = max(0, depth - 1)
            continue
        if current is None:
            continue
        field = _PANOS_FIELD.match(stripped)
        if field:
            current[field.group(1).lower()] = field.group(2).strip()
    return tuple(policies)


def _panos_entry(
    name: str, fields: dict, sequence: int, source_command: str
) -> PolicyRoute:
    action = (fields.get("action") or "").lower()
    unresolved: list[str] = []

    # A source ZONE is not an ingress interface. Which interfaces are in a
    # zone is knowable, but not from this command — so it is recorded as
    # unresolved, leaving the rule undecidable rather than pretending the
    # zone name is an interface name and matching on it.
    zone = _panos_any(fields.get("from"))
    if zone:
        unresolved.append(f"source zone {zone}")
    # Application matching is layer 7. Nothing in a path question can
    # decide it, so a rule that turns on it can never be confirmed.
    application = _panos_any(fields.get("application/service"))
    if application:
        unresolved.append(f"application/service {application}")

    return PolicyRoute(
        sequence=sequence,
        source=_clean_prefix(_panos_any(fields.get("source"))),
        destination=_clean_prefix(_panos_any(fields.get("destination"))),
        ingress_interface=None,
        next_hop=_panos_any(fields.get("next-hop")),
        egress_interface=_panos_any(
            fields.get("forwarding-egress-if/vsys")
            or fields.get("forwarding-egress-if")
        ),
        # "no-pbf" means explicitly DO NOT policy-route this, and "discard"
        # is a drop the firewall model owns — neither redirects, and
        # neither may be read as a forward.
        disabled=action in {"no-pbf", "discard", "disabled"},
        name=name,
        unresolved_matches=tuple(unresolved),
        source_command=source_command,
    )


def _panos_any(value: object) -> str | None:
    """PAN-OS writes an unconstrained match as "any"."""

    text = _clean(value)
    if text is None or text.lower() in {"any", "none"}:
        return None
    # A bracketed list is more than one value; none of them is safely a
    # single prefix, so the caller sees the raw text and treats it as
    # unresolved rather than mis-parsing the first entry as the whole set.
    return text


# -- FRRouting PBR ---------------------------------------------------------
# FRR has its own daemon and its own grammar — neither route-map nor
# iproute2. `show pbr map` prints the rules, `show pbr interface` prints
# which interface each map is applied to, and the binding is half the fact
# exactly as it is on IOS.
#
# Two states this output distinguishes and a naive read would not:
#
#   "pbrd is not running"   the daemon that would answer is DOWN. This is
#                           not "no policy routing" — it is Atlas being
#                           unable to tell, and it must stay unevaluated.
#   "Installed: no"         the rule is configured but NOT in the kernel,
#                           so it is not forwarding anything. Reading it
#                           as live would divert a flow the router does
#                           not divert.
#
# Both were observed on a real FRR 8.4 router, not inferred.

PBRD_DOWN = "pbrd is not running"

_FRR_MAP = re.compile(r"^\s*pbr-map\s+(\S+)\s+valid:\s*(\S+)", re.IGNORECASE)
_FRR_SEQ = re.compile(r"^\s*Seq:\s*(\d+)\s+rule:\s*(\d+)", re.IGNORECASE)
_FRR_INSTALLED = re.compile(r"^\s*Installed:\s*(\S+)", re.IGNORECASE)
_FRR_MATCH = re.compile(
    r"^\s*(SRC IP|DST IP|IP Protocol|SRC Port|DST Port)\s+Match:\s*(\S+)",
    re.IGNORECASE,
)
_FRR_NEXTHOP = re.compile(r"^\s*nexthop\s+(\S+)", re.IGNORECASE)
_FRR_BINDING = re.compile(
    r"^\s*(\S+?)\(\d+\)\s+with\s+pbr-policy\s+(\S+)", re.IGNORECASE
)


def frr_pbr_is_readable(text: str | None) -> bool:
    """Whether the PBR daemon actually answered.

    Give this the JSON form's output, not the text form's. `show pbr map`
    is silent BOTH when pbrd is down and when it is up with nothing
    configured, so it can never distinguish them; `show pbr map json`
    prints "[ ]" for the second, which is positive evidence someone
    answered. Both observed on a real FRR 8.4 router.

    A router whose pbrd is down has told us nothing about policy routing.
    Recording that as "captured, and there are none" would assert an
    absence nobody checked.

    EMPTY output is not readable either, and that is the subtle half. On a
    real FRR 8.4 router "pbrd is not running" goes to STDERR while stdout
    comes back empty — so a check that only looks for the message passes
    an empty string straight through and reports no policy routing on a
    router that never answered. A pbrd that IS up but has no maps also
    prints nothing, so emptiness cannot distinguish the two at all.

    The cost is that a genuinely PBR-free router stays unevaluated instead
    of confirmed-empty. That is the right direction to be wrong in: it
    under-claims what Atlas knows rather than asserting an absence it
    cannot see.
    """

    body = (text or "").strip()
    if not body:
        return False
    return PBRD_DOWN not in body.lower()


def parse_frr_pbr_interfaces(text: str) -> dict[str, list[str]]:
    """Map name -> interfaces it is applied to, from `show pbr interface`."""

    bindings: dict[str, list[str]] = {}
    for raw in (text or "").splitlines():
        match = _FRR_BINDING.match(raw)
        if match:
            bindings.setdefault(match.group(2), []).append(match.group(1))
    return bindings


def parse_frr_pbr_maps(
    text: str,
    *,
    bindings: dict[str, list[str]] | None = None,
    source_command: str = "show pbr map",
) -> tuple[PolicyRoute, ...]:
    if not frr_pbr_is_readable(text):
        return ()

    policies: list[PolicyRoute] = []
    name: str | None = None
    entry: dict | None = None

    def flush() -> None:
        if entry is None or name is None:
            return
        interfaces = (bindings or {}).get(name) or []
        port = _as_int(entry.get("dst port"))
        for interface in sorted(interfaces):
            policies.append(PolicyRoute(
                sequence=entry["sequence"],
                source=_clean_prefix(entry.get("src ip")),
                destination=_clean_prefix(entry.get("dst ip")),
                protocol=_clean(entry.get("ip protocol")),
                destination_ports=(port,) if port is not None else (),
                ingress_interface=interface,
                next_hop=entry.get("nexthop"),
                # Configured but not in the kernel forwards nothing.
                disabled=not entry.get("installed", False),
                name=f"{name} seq {entry['sequence']}",
                source_command=source_command,
            ))

    for raw in (text or "").splitlines():
        header = _FRR_MAP.match(raw)
        if header:
            flush()
            entry = None
            name = header.group(1)
            continue
        sequence = _FRR_SEQ.match(raw)
        if sequence:
            flush()
            entry = {"sequence": int(sequence.group(1))}
            continue
        if entry is None:
            continue
        installed = _FRR_INSTALLED.match(raw)
        if installed:
            # The FIRST Installed line belongs to the rule; a later one
            # belongs to its nexthop, and a nexthop installed under a rule
            # that is not must not make the rule look live.
            if "installed" not in entry:
                entry["installed"] = installed.group(1).lower() == "yes"
            continue
        criterion = _FRR_MATCH.match(raw)
        if criterion:
            entry[criterion.group(1).lower()] = criterion.group(2)
            continue
        nexthop = _FRR_NEXTHOP.match(raw)
        if nexthop:
            entry["nexthop"] = nexthop.group(1)
    flush()
    return tuple(policies)


# -- shared helpers --------------------------------------------------------

def _clean(value: object) -> str | None:
    text = str(value or "").strip().strip('"')
    return text or None


def _clean_prefix(value: object) -> str | None:
    """A prefix, however the platform spelled it.

    FortiOS writes "10.0.0.0 255.255.255.0"; iproute2 writes a bare
    address for a /32. Both become CIDR, and anything unrecognisable
    becomes None rather than a prefix that does not mean what it says.
    """

    text = _clean(value)
    if text is None:
        return None
    parts = text.split()
    if len(parts) == 2:
        try:
            return str(ip_network(f"{parts[0]}/{parts[1]}", strict=False))
        except ValueError:
            return None
    try:
        return str(ip_network(text, strict=False))
    except ValueError:
        pass
    try:
        ip_address(text)
    except ValueError:
        return None
    return f"{text}/32"


def _as_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def policy_route_dicts(policies) -> tuple[dict, ...]:
    """Plain dicts for the evidence blob, in evaluation order."""

    return tuple(
        {
            "sequence": policy.sequence,
            "source": policy.source,
            "destination": policy.destination,
            "protocol": policy.protocol,
            "destination_ports": list(policy.destination_ports),
            "ingress_interface": policy.ingress_interface,
            "next_hop": policy.next_hop,
            "egress_interface": policy.egress_interface,
            "table": policy.table,
            "disabled": policy.disabled,
            "name": policy.name,
            "unresolved_matches": list(policy.unresolved_matches),
            "source_command": policy.source_command,
        }
        for policy in sorted(policies, key=lambda item: item.sequence)
    )
