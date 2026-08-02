"""Structured question understanding (PR-167, Part 1).

Turn an operator's sentence into an :class:`InvestigationRequest`.

Deterministic throughout: fixed vocabularies for protocols,
applications, severities and directions; fixed regex shapes for
endpoints, interfaces, VLANs, VRFs and addresses. There is no scoring,
no similarity, and no inference — a term Atlas does not recognise is
simply not extracted, which is why the request can be shown to the
operator and checked.

The one rule that matters: never invent scope. "How is BGP between
Mumbai and Hyderabad?" names two endpoints; "Is the network healthy?"
names none, and must stay an estate-wide question.
"""

from __future__ import annotations

import re

from .models import InvestigationRequest


# -- vocabularies ----------------------------------------------------------

PROTOCOLS: dict[str, tuple[str, ...]] = {
    "bgp": ("bgp", "border gateway"),
    "ospf": ("ospf",),
    "eigrp": ("eigrp",),
    "isis": ("is-is", "isis"),
    "hsrp": ("hsrp", "vrrp", "first hop redundancy", "fhrp"),
    "stp": ("stp", "spanning tree", "spanning-tree"),
    "vpn": ("vpn", "ipsec", "tunnel", "dmvpn"),
    "mpls": ("mpls", "ldp"),
    "lldp": ("lldp", "cdp"),
    "dns": ("dns",),
    "dhcp": ("dhcp",),
    "ntp": ("ntp",),
    "snmp": ("snmp",),
}

APPLICATIONS: dict[str, tuple[str, ...]] = {
    "https": ("https", "port 443", "tls", "ssl"),
    "http": ("http ", "port 80"),
    "ssh": ("ssh", "port 22"),
    "sap": ("sap",),
    "citrix": ("citrix",),
    "voice": ("voice", "voip", "sip", "telephony"),
    "video": ("video", "conferencing"),
    "backup": ("backup",),
    "email": ("email", "smtp", "exchange", "outlook"),
    "file-sharing": ("smb", "cifs", "nfs", "file share"),
}

SEVERITIES: dict[str, tuple[str, ...]] = {
    "down": ("down", "outage", "offline", "unreachable", "dead"),
    "unstable": ("flap", "flapping", "unstable", "intermittent",
                 "bouncing", "resetting"),
    "degraded": ("degraded", "errors", "packet loss", "dropping",
                 "drops", "failing"),
    "slow": ("slow", "latency", "latent", "sluggish", "timeout",
             "timing out", "performance"),
}

DIRECTIONS: dict[str, tuple[str, ...]] = {
    "inbound": ("inbound", "incoming", "received", "ingress"),
    "outbound": ("outbound", "outgoing", "advertised", "egress", "sent"),
}

TIME_RANGES: tuple[tuple[str, str], ...] = (
    ("last 24 hours", ("last 24 hours", "past 24 hours", "last day",
                       "past day", "today")),
    ("yesterday", ("yesterday", "overnight", "last night")),
    ("last week", ("last week", "past week", "last 7 days",
                   "past 7 days")),
    ("last hour", ("last hour", "past hour", "last 60 minutes")),
    ("last month", ("last month", "past month", "last 30 days")),
)

# -- shapes ----------------------------------------------------------------

# "between X and Y", "from X to Y", "X to Y", "can X reach Y"
_ENDPOINT_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbetween\s+([\w.-]+)\s+and\s+([\w.-]+)", re.I),
    re.compile(r"\bfrom\s+([\w.-]+)\s+(?:to|and)\s+([\w.-]+)", re.I),
    re.compile(r"\bcan\s+([\w.-]+)\s+reach\s+([\w.-]+)", re.I),
    re.compile(
        r"\b([\w.-]+)\s+(?:cannot|can't|cant)\s+reach\s+([\w.-]+)", re.I
    ),
    re.compile(r"\b([\w.-]+)\s+(?:is\s+)?unreachable\s+from\s+([\w.-]+)",
               re.I),
)

# Interface shapes: Gi0/1, GigabitEthernet0/0/1, eth2, Te1/0/1, ge-0/0/1,
# port-channel10, Vlan300 handled separately.
_INTERFACE = re.compile(
    r"\b((?:gigabitethernet|tengigabitethernet|fastethernet|ethernet|"
    r"port-?channel|bundle-ether|xe|ge|te|gi|fa|eth|em|swp)"
    r"[-\s]?\d+(?:[/:]\d+)*(?:\.\d+)?)\b",
    re.I,
)
_VLAN = re.compile(r"\bvlan\s*(\d{1,4})\b", re.I)
_VRF = re.compile(r"\bvrf\s+([\w.-]+)", re.I)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")

# Words that appear in endpoint position but are not entities.
# NB: "hq", "dc", "branch" and similar are NOT here — they are real
# site names in many estates, and excluding them would make those
# sites permanently un-investigable.
_NOT_AN_ENTITY = frozenset((
    "the", "a", "an", "and", "or", "it", "them", "us", "here", "there",
    "everything", "anything", "network", "enterprise", "site", "sites",
    "device", "devices", "this", "that", "any", "all", "both",
    "each", "our", "my", "your", "these", "those", "now", "then",
    "yesterday", "today",
))


def _folded(question: str) -> str:
    return " ".join(str(question or "").casefold().split())


def _match_vocabulary(folded: str, vocabulary: dict[str, tuple[str, ...]]
                      ) -> str:
    """The first vocabulary key whose term appears. Single alphanumeric
    terms match on word boundaries so "bgp" never fires inside a longer
    token; decorated terms match as substrings."""

    for key, terms in vocabulary.items():
        for term in terms:
            if " " in term.strip() or not term.strip().isalnum():
                if term in folded:
                    return key
            elif re.search(rf"\b{re.escape(term)}\b", folded):
                return key
    return ""


def _match_all(folded: str, vocabulary: dict[str, tuple[str, ...]]
               ) -> tuple[str, ...]:
    found = []
    for key, terms in vocabulary.items():
        for term in terms:
            hit = (
                term in folded if (" " in term.strip()
                                   or not term.strip().isalnum())
                else re.search(rf"\b{re.escape(term)}\b", folded)
            )
            if hit:
                found.append(key)
                break
    return tuple(found)


def _clean_entity(value: str) -> str:
    return str(value or "").strip().strip(".,;:?!\"'").strip()


def _endpoints(question: str) -> tuple[str, str]:
    cleaned = re.sub(r"[?!,]", " ", str(question or ""))
    for pattern in _ENDPOINT_SHAPES:
        match = pattern.search(cleaned)
        if not match:
            continue
        first = _clean_entity(match.group(1))
        second = _clean_entity(match.group(2))
        if (first.casefold() in _NOT_AN_ENTITY
                or second.casefold() in _NOT_AN_ENTITY):
            continue
        if not first or not second:
            continue
        # "X unreachable from Y" reads Y -> X.
        if "unreachable" in pattern.pattern:
            return second, first
        return first, second
    return "", ""


def _time_range(folded: str) -> str:
    for label, terms in TIME_RANGES:
        for term in terms:
            if term in folded:
                return label
    return ""


def extract(question: str, *, known_sites: tuple[str, ...] = ()
            ) -> InvestigationRequest:
    """Understand one question structurally.

    ``known_sites`` are the site names Atlas has actually derived; a
    bare site mention is only extracted when Atlas knows that site,
    which keeps the request from naming scope that does not exist.
    """

    text = str(question or "")
    folded = _folded(text)
    source, destination = _endpoints(text)

    interfaces = tuple(dict.fromkeys(
        _clean_entity(item) for item in _INTERFACE.findall(text)
    ))
    vlans = tuple(dict.fromkeys(_VLAN.findall(text)))
    vrfs = tuple(dict.fromkeys(
        _clean_entity(item) for item in _VRF.findall(text)
    ))
    addresses = tuple(dict.fromkeys(_IPV4.findall(text)))

    # Bare site mentions: only names Atlas already knows. Deduplicated
    # case-insensitively and recorded in ATLAS's spelling, so "Mumbai"
    # and the discovered site "mumbai" are one entry, not two.
    sites: list[str] = []
    seen_sites: set[str] = set()
    for site in known_sites:
        name = str(site or "").strip()
        folded_name = name.casefold()
        if not name or name in ("unknown", "ambiguous"):
            continue
        if folded_name in seen_sites:
            continue
        # The name must stand alone. "delhi" in "delhi-r1" names a
        # DEVICE, not the delhi scope — reading it as the scope turned
        # "Find delhi-r1" into a site summary, which is precisely the
        # substitution this PR exists to stop.
        if re.search(rf"\b{re.escape(folded_name)}\b(?![-.]\w)", folded):
            sites.append(name)
            seen_sites.add(folded_name)

    return InvestigationRequest(
        question=text.strip(),
        protocol=_match_vocabulary(folded, PROTOCOLS),
        source=source,
        destination=destination,
        sites=tuple(sites),
        interfaces=interfaces,
        vlans=vlans,
        vrfs=vrfs,
        applications=_match_all(folded, APPLICATIONS),
        addresses=addresses,
        time_range=_time_range(folded),
        severity=_match_vocabulary(folded, SEVERITIES),
        direction=_match_vocabulary(folded, DIRECTIONS),
    )
