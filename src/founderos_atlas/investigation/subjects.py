"""The subject registry: what a question can be ABOUT (PR-171).

Before this module, the protocol vocabulary was an inline dict in
``extraction.py`` — thirteen protocols, correct, and destined to become
unmaintainable at the two-year horizon of hundreds of vendors and
protocols. This registry is the seam: adding IS-IS or VXLAN is one
descriptor here, and nothing else changes — not the parser, not the
router, not a template.

A :class:`SubjectDescriptor` is DATA, deliberately, on the same
principle as the policy packs and the intent registry: descriptors
declare names and links to evidence; they never carry code. That is
also why this is a registry and not a plug-in system — loading
third-party protocol code would be a security surface, a stability
surface and a support surface that declarative data simply does not
have.

``policy_tags`` is the link that makes configuration validation work:
it names the tags a policy pack uses for rules about this subject, so
the validation template can select the EXISTING policy engine's rules
for it rather than re-implementing any matching. A subject with no
tags cannot be validated — and Atlas says so rather than passing it.
"""

from __future__ import annotations

from dataclasses import dataclass


KIND_PROTOCOL = "protocol"
KIND_DOMAIN = "domain"        # a subject that is not one protocol —
#                               "configuration", "interfaces"


@dataclass(frozen=True)
class SubjectDescriptor:
    """One thing a question can be about, fully declared.

    PR-172 adds two defaulted fields. ``validation_title`` overrides
    the derived "<label> configuration" heading when that phrasing
    reads badly; ``platform_capability`` names the collection-layer
    capability (:mod:`founderos_atlas.platforms.capabilities`) whose
    evidence underlies this subject — the link a future "Unsupported:
    no platform can collect this" cause reads. Neither is required for
    a subject to be validatable: capability is DISCOVERED from
    ``policy_tags`` against the installed pack, never declared here.
    """

    key: str
    label: str
    terms: tuple[str, ...]          # the operator's words for it
    kind: str = KIND_PROTOCOL
    evidence_kinds: tuple[str, ...] = ()   # OIR vocabulary names
    policy_tags: tuple[str, ...] = ()      # policy-pack tags that judge it
    validation_title: str = ""             # "" -> "<label> configuration"
    platform_capability: str = ""          # collection capability name


# Seeded from the PR-167 protocol vocabulary — the DATA is unchanged,
# only its home moved, so extraction behaves exactly as before. The two
# non-protocol subjects (configuration, interfaces) exist so a question
# like "is all the FOO configuration fine?" still has a recognised
# subject to hang an honest refusal on.
SUBJECTS: tuple[SubjectDescriptor, ...] = (
    SubjectDescriptor(
        "bgp", "BGP", ("bgp", "border gateway"),
        evidence_kinds=("BGP Observations",), policy_tags=("bgp",),
        platform_capability="bgp",
    ),
    SubjectDescriptor(
        "ospf", "OSPF", ("ospf",),
        evidence_kinds=("OSPF Observations",), policy_tags=("ospf",),
        platform_capability="ospf",
    ),
    SubjectDescriptor("eigrp", "EIGRP", ("eigrp",)),
    SubjectDescriptor("isis", "IS-IS", ("is-is", "isis")),
    SubjectDescriptor(
        "hsrp", "First-hop redundancy",
        ("hsrp", "vrrp", "first hop redundancy", "fhrp"),
        platform_capability="first-hop-redundancy",
    ),
    SubjectDescriptor(
        "stp", "Spanning tree", ("stp", "spanning tree", "spanning-tree"),
        platform_capability="stp",
    ),
    SubjectDescriptor("vpn", "VPN", ("vpn", "ipsec", "tunnel", "dmvpn")),
    SubjectDescriptor("mpls", "MPLS", ("mpls", "ldp")),
    SubjectDescriptor(
        "lldp", "Neighbour discovery", ("lldp", "cdp"),
        platform_capability="lldp",
    ),
    SubjectDescriptor("dns", "DNS", ("dns",)),
    SubjectDescriptor("dhcp", "DHCP", ("dhcp",)),
    # NTP and SNMP have starter-pack policies, but those rules carry the
    # tags "time" / "observability" — not the subject key. A tag is only
    # declared here when it REALLY selects that subject's rules; a wrong
    # tag would make validation confidently judge the wrong thing.
    SubjectDescriptor("ntp", "NTP", ("ntp",)),
    SubjectDescriptor("snmp", "SNMP", ("snmp",)),
    # -- non-protocol subjects (PR-171) ------------------------------
    SubjectDescriptor(
        "configuration", "Configuration", ("configuration", "config"),
        kind=KIND_DOMAIN, evidence_kinds=("Configuration Memory",),
        platform_capability="configuration",
    ),
    SubjectDescriptor(
        "interfaces", "Interfaces", ("interface", "interfaces"),
        kind=KIND_DOMAIN, evidence_kinds=("Interface Inventory",),
        platform_capability="interfaces",
    ),
)

SUBJECT_BY_KEY: dict[str, SubjectDescriptor] = {
    item.key: item for item in SUBJECTS
}

# The exact shape extraction.py consumed before this registry existed:
# protocol key -> terms tuple, protocol-kind subjects only. Keeping the
# derived view identical is what keeps extraction behaviour identical.
PROTOCOLS: dict[str, tuple[str, ...]] = {
    item.key: item.terms for item in SUBJECTS if item.kind == KIND_PROTOCOL
}

# Domain subjects, matched only after every protocol has had its
# chance — "ospf configuration" is about OSPF, not about configuration
# in general.
DOMAIN_SUBJECTS: dict[str, tuple[str, ...]] = {
    item.key: item.terms for item in SUBJECTS if item.kind == KIND_DOMAIN
}


def subject(key: str) -> SubjectDescriptor | None:
    return SUBJECT_BY_KEY.get(str(key or ""))


def label_for(key: str) -> str:
    descriptor = subject(key)
    return descriptor.label if descriptor else str(key or "").upper()
