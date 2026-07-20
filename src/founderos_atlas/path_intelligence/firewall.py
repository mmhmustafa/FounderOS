"""Firewall policy evaluated against a declared packet.

The ACL reader in ``policy`` understands a router's access-lists. A
firewall states its policy somewhere else entirely — the enforced
chain that discovery already captured into device metadata — and that
is where the answer lives on a path that crosses a perimeter. Without
this, a trace across a default-deny firewall reports "no captured
policy at this hop" and reads as healthy, which is the one place it
must not.

Rules of evidence, as everywhere else:

- The enforced chain is *observed* state (discovery read the running
  counters), not a configuration file someone might have edited since.
- Matching is three-valued. A rule qualifier Atlas does not model
  makes the hop indeterminate — "this rule may apply" — never a
  guessed permit or deny.
- ``LOG`` is not a verdict. iptables keeps walking the chain after it,
  so evaluation does too; treating it as terminal would silently
  invent a permit.
- The packet being traced is the FIRST of its flow, so a rule matching
  only ``ESTABLISHED``/``RELATED`` state cannot admit it. That is
  stated rather than assumed away.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import re
from typing import Any

from .policy import INDETERMINATE, MATCH, NO_MATCH, canonical_interface


ACTION_PERMIT = "permit"
ACTION_DENY = "deny"

# iptables targets that end the walk, and what they mean for a packet.
_TERMINAL = {
    "ACCEPT": ACTION_PERMIT,
    "DROP": ACTION_DENY,
    "REJECT": ACTION_DENY,
}

_DPORT = re.compile(
    r"\b(?:tcp|udp)\s+dpt:(\d+)", re.IGNORECASE
)
_DPORTS = re.compile(
    r"\bmultiport\s+dports\s+([0-9,:\s]+)", re.IGNORECASE
)
_STATE = re.compile(r"\bstate\s+([A-Z,]+)", re.IGNORECASE)


@dataclass(frozen=True)
class FirewallRule:
    number: int
    target: str
    protocol: str
    in_interface: str | None
    out_interface: str | None
    source: str
    destination: str
    detail: str | None = None
    packets: int | None = None

    def describe(self) -> str:
        parts = [f"rule {self.number}", self.target, self.protocol]
        if self.in_interface:
            parts.append(f"in {self.in_interface}")
        if self.out_interface:
            parts.append(f"out {self.out_interface}")
        parts.append(f"src {self.source}")
        parts.append(f"dst {self.destination}")
        if self.detail:
            parts.append(self.detail)
        return " ".join(str(part) for part in parts)


@dataclass(frozen=True)
class FirewallPolicy:
    chain: str
    default_policy: str
    rules: tuple[FirewallRule, ...]

    @property
    def default_action(self) -> str | None:
        return _TERMINAL.get(str(self.default_policy).upper())


@dataclass(frozen=True)
class FirewallVerdict:
    kind: str                      # permit | deny | default-deny | default-permit | indeterminate
    rule: FirewallRule | None
    reason: str


def firewall_from_metadata(metadata: Any) -> FirewallPolicy | None:
    """Read the captured chain out of a snapshot device's metadata.

    Rules serialize as ordered key/value pairs in the snapshot; both
    that form and a plain mapping are accepted, so this survives a
    change of serializer without inventing a migration.
    """

    if not isinstance(metadata, dict):
        return None
    captured = metadata.get("firewall")
    if not isinstance(captured, dict):
        return None
    rules: list[FirewallRule] = []
    for entry in captured.get("rules") or ():
        fields = _as_mapping(entry)
        if fields is None:
            continue
        try:
            rules.append(
                FirewallRule(
                    number=int(fields.get("number") or 0),
                    target=str(fields.get("target") or ""),
                    protocol=str(fields.get("protocol") or "all"),
                    in_interface=fields.get("in_interface") or None,
                    out_interface=fields.get("out_interface") or None,
                    source=str(fields.get("source") or "0.0.0.0/0"),
                    destination=str(fields.get("destination") or "0.0.0.0/0"),
                    detail=fields.get("detail") or None,
                    packets=fields.get("packets"),
                )
            )
        except (TypeError, ValueError):
            continue
    chain = str(captured.get("chain") or "FORWARD")
    default_policy = str(captured.get("default_policy") or "")
    if not rules and not default_policy:
        return None
    return FirewallPolicy(
        chain=chain,
        default_policy=default_policy,
        rules=tuple(sorted(rules, key=lambda rule: rule.number)),
    )


def evaluate_firewall(
    policy: FirewallPolicy,
    intent: dict,
    *,
    ingress: str | None = None,
    egress: str | None = None,
    destination_addresses: tuple[str, ...] = (),
    source_addresses: tuple[str, ...] = (),
) -> FirewallVerdict:
    """Walk the chain for the declared packet, first terminal match wins."""

    for rule in policy.rules:
        verdict = match_firewall_rule(
            rule,
            intent,
            ingress=ingress,
            egress=egress,
            destination_addresses=destination_addresses,
            source_addresses=source_addresses,
        )
        if verdict == NO_MATCH:
            continue
        action = _TERMINAL.get(rule.target.upper())
        if action is None:
            # LOG and friends annotate and fall through — the walk
            # continues exactly as the kernel's would.
            continue
        if verdict == INDETERMINATE:
            return FirewallVerdict(
                kind=INDETERMINATE,
                rule=rule,
                reason=(
                    f"{policy.chain} {rule.describe()} may apply to this "
                    "packet, but the declared intent cannot settle it"
                ),
            )
        return FirewallVerdict(
            kind=action,
            rule=rule,
            reason=f"{policy.chain} {rule.describe()}",
        )
    default = policy.default_action
    if default == ACTION_DENY:
        return FirewallVerdict(
            kind="default-deny",
            rule=None,
            reason=(
                f"no rule in chain {policy.chain} matches this packet and "
                f"the chain's default policy is {policy.default_policy}"
            ),
        )
    if default == ACTION_PERMIT:
        return FirewallVerdict(
            kind="default-permit",
            rule=None,
            reason=(
                f"no rule in chain {policy.chain} matches this packet and "
                f"the chain's default policy is {policy.default_policy}"
            ),
        )
    return FirewallVerdict(
        kind=INDETERMINATE,
        rule=None,
        reason=(
            f"no rule in chain {policy.chain} matches and its default "
            "policy could not be read"
        ),
    )


def match_firewall_rule(
    rule: FirewallRule,
    intent: dict,
    *,
    ingress: str | None = None,
    egress: str | None = None,
    destination_addresses: tuple[str, ...] = (),
    source_addresses: tuple[str, ...] = (),
) -> str:
    """Three-valued match of one chain rule against the declared packet."""

    checks = [
        _match_interface(rule.in_interface, ingress),
        _match_interface(rule.out_interface, egress),
        _match_protocol(rule.protocol, str(intent.get("protocol") or "")),
        _match_network(rule.source, source_addresses),
        _match_network(rule.destination, destination_addresses),
        _match_detail(rule, intent),
    ]
    if any(check == NO_MATCH for check in checks):
        return NO_MATCH
    if any(check == INDETERMINATE for check in checks):
        return INDETERMINATE
    return MATCH


def _as_mapping(entry: Any) -> dict | None:
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, (list, tuple)):
        try:
            return {str(key): value for key, value in entry}
        except (TypeError, ValueError):
            return None
    return None


def _match_interface(constraint: str | None, actual: str | None) -> str:
    if not constraint or constraint in ("*", "any"):
        return MATCH
    if not actual:
        # The rule cares about direction and Atlas does not know which
        # way the packet crosses this hop.
        return INDETERMINATE
    return (
        MATCH
        if canonical_interface(constraint) == canonical_interface(actual)
        else NO_MATCH
    )


def _match_protocol(constraint: str, declared: str) -> str:
    folded = (constraint or "all").casefold()
    if folded in ("all", "ip", "0"):
        return MATCH
    if not declared:
        return INDETERMINATE
    return MATCH if folded == declared.casefold() else NO_MATCH


def _match_network(constraint: str, addresses: tuple[str, ...]) -> str:
    value = (constraint or "").strip()
    if not value or value in ("0.0.0.0/0", "anywhere", "::/0"):
        return MATCH
    try:
        network = ip_network(value, strict=False)
    except ValueError:
        return INDETERMINATE
    if not addresses:
        return INDETERMINATE
    for address in addresses:
        try:
            if ip_address(address) in network:
                return MATCH
        except ValueError:
            continue
    return NO_MATCH


def _match_detail(rule: FirewallRule, intent: dict) -> str:
    detail = (rule.detail or "").strip()
    if not detail:
        return MATCH
    remaining = detail

    state = _STATE.search(detail)
    if state:
        states = {item.strip().upper() for item in state.group(1).split(",")}
        # The traced packet opens the flow; it is NEW by definition, so
        # a rule admitting only replies cannot be the one that admits it.
        if states and states <= {"ESTABLISHED", "RELATED"}:
            return NO_MATCH
        if "NEW" not in states:
            return INDETERMINATE
        remaining = _STATE.sub("", remaining)

    port_verdict = MATCH
    single = _DPORT.search(detail)
    multi = _DPORTS.search(detail)
    declared_port = str(intent.get("port") or "")
    if single or multi:
        if not declared_port.isdigit():
            return INDETERMINATE
        wanted = int(declared_port)
        if single:
            port_verdict = MATCH if int(single.group(1)) == wanted else NO_MATCH
            remaining = _DPORT.sub("", remaining)
        else:
            port_verdict = (
                MATCH if _in_multiport(multi.group(1), wanted) else NO_MATCH
            )
            remaining = _DPORTS.sub("", remaining)
    if port_verdict == NO_MATCH:
        return NO_MATCH

    # Anything left that Atlas does not model narrows the rule in a way
    # the declared intent cannot settle.
    leftover = remaining.strip(" ,")
    if leftover:
        return INDETERMINATE
    return port_verdict


def _in_multiport(spec: str, port: int) -> bool:
    for item in spec.replace(" ", "").split(","):
        if not item:
            continue
        if ":" in item:
            low, _, high = item.partition(":")
            try:
                if int(low) <= port <= int(high):
                    return True
            except ValueError:
                continue
        else:
            try:
                if int(item) == port:
                    return True
            except ValueError:
                continue
    return False
