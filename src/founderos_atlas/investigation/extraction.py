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

# PR-171: the protocol vocabulary moved to the subject REGISTRY
# (subjects.py) — one seam for the two-year horizon of new protocols.
# The derived dict here has exactly the shape and content the inline
# dict had, so extraction behaviour is unchanged and the existing
# extraction tests prove it.
from .subjects import DOMAIN_SUBJECTS, PROTOCOLS  # noqa: E402  (re-export)

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

# PR-171: the operational OBJECTIVE — what KIND of answer is wanted.
# Fixed vocabularies, word-anchored, no scoring, exactly like every
# other dimension here. When several match, the most specific wins in
# the fixed precedence below (assess last — it is also the default).
OBJECTIVE_VALIDATE = "validate"
OBJECTIVE_ASSESS = "assess"
OBJECTIVE_LOCATE = "locate"
OBJECTIVE_EXPLAIN = "explain"
OBJECTIVE_COMPARE = "compare"
OBJECTIVE_FORECAST = "forecast"

# Validation is TWO signals, not one. "Configuration" alone is a
# subject ("show me the OSPF configuration" is a lookup); a judgement
# word alone is an assessment ("is OSPF fine?"). Only together do they
# ask Atlas to JUDGE a configuration — plus a few self-contained terms
# that carry both meanings in one word.
VALIDATE_CONTEXT_TERMS: tuple[str, ...] = (
    "configuration", "config", "configured", "set up",
)
VALIDATE_JUDGEMENT_TERMS: tuple[str, ...] = (
    "fine", "correct", "correctly", "right", "ok", "properly",
    "standard", "good",
)
VALIDATE_STANDALONE_TERMS: tuple[str, ...] = (
    "misconfigured", "compliant", "compliance",
    "correctly configured", "configured correctly",
)

OBJECTIVES: dict[str, tuple[str, ...]] = {
    OBJECTIVE_EXPLAIN: ("why", "cause", "reason", "root cause"),
    OBJECTIVE_COMPARE: ("changed", "differs", "difference", "drift"),
    OBJECTIVE_FORECAST: ("will", "risk", "predict", "impact"),
    OBJECTIVE_LOCATE: ("find", "where is", "show me", "which device"),
    OBJECTIVE_ASSESS: ("healthy", "health", "working", "up", "status",
                       "state"),
}

# PR-173: words that ask about behaviour OVER TIME. Atlas retains no
# state history — a single discovery cannot distinguish a link that
# flapped from one that was simply down when observed — so a question
# carrying one of these is refused honestly, quoting the word. Fixed
# vocabulary, word-anchored, like every other dimension here.
# "stability"/"stable" are included: "is BGP stable?" asks about time,
# not about this instant.
TEMPORAL_TERMS: tuple[str, ...] = (
    "flapping", "flapped", "flaps", "flap",
    "unstable", "instability", "stability", "stable",
    "intermittent", "intermittently", "keeps dropping",
)

# Most specific first; assess is both last and the default. The order
# is part of the contract: a question matching two objectives always
# resolves the same way, and the basis says which terms decided it.
OBJECTIVE_PRECEDENCE = (
    OBJECTIVE_VALIDATE, OBJECTIVE_EXPLAIN, OBJECTIVE_COMPARE,
    OBJECTIVE_FORECAST, OBJECTIVE_LOCATE, OBJECTIVE_ASSESS,
)

# PR-171: the positive scope. "Across the enterprise" is a REAL,
# resolved scope — not the absence of one. Conflating "named no place"
# with "asked about everything" is precisely what made an
# enterprise-scoped OSPF question read as unscoped.
SCOPE_ENTERPRISE = "enterprise"
SCOPE_SITES = "sites"
SCOPE_DEVICES = "devices"
SCOPE_INTERFACES = "interfaces"

ENTERPRISE_SCOPE_TERMS: tuple[str, ...] = (
    "across the enterprise", "enterprise-wide", "enterprise wide",
    "the whole enterprise", "the entire enterprise", "everywhere",
    "all sites", "every site", "all devices", "every device",
    "fleet-wide", "fleet wide", "the whole network", "the entire network",
)

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


def _objective(folded: str, *, has_subject: bool) -> tuple[str, list[str]]:
    """(objective, basis) — the most specific objective the question's
    own words support, with the terms that decided it.

    ``validate`` REQUIRES a subject. "Is the network fine?" must stay
    an assessment: without a subject there is nothing whose
    configuration could be judged, and reading it as validation would
    send generic questions to the compliance engine (risk R2).
    """

    # Validation first, and gated twice: it needs a SUBJECT (R2 — "is
    # the network fine?" stays an assessment) and it needs either a
    # self-contained validation word or configuration-context AND a
    # judgement word together. "Show me the OSPF configuration" is a
    # lookup; "is the OSPF configuration fine" is a validation.
    if has_subject:
        standalone = _match_all_terms(folded, VALIDATE_STANDALONE_TERMS)
        context_hits = _match_all_terms(folded, VALIDATE_CONTEXT_TERMS)
        judgement_hits = _match_all_terms(folded, VALIDATE_JUDGEMENT_TERMS)
        if standalone or (context_hits and judgement_hits):
            hits = list(standalone) + list(context_hits) + \
                list(judgement_hits)
            terms = ", ".join(f"“{hit}”" for hit in hits)
            return OBJECTIVE_VALIDATE, [
                "objective validate: configuration terminology detected "
                f"({terms})"
            ]

    for objective in OBJECTIVE_PRECEDENCE:
        if objective == OBJECTIVE_VALIDATE:
            continue                     # handled above, with its gates
        hits = list(_match_all_terms(folded, OBJECTIVES[objective]))
        if hits:
            terms = ", ".join(f"“{hit}”" for hit in hits)
            return objective, [f"objective {objective}: the question "
                               f"says {terms}"]
    return OBJECTIVE_ASSESS, ["objective assess: the default — no more "
                              "specific objective terminology was used"]


def _match_all_terms(folded: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Every term that appears, with the same boundary rules as the
    vocabularies above: bare single tokens at word boundaries, phrases
    and decorated terms as substrings."""

    hits = []
    for term in terms:
        if " " in term.strip() or not term.strip().isalnum():
            if term in folded:
                hits.append(term)
        elif re.search(rf"\b{re.escape(term)}\b", folded):
            hits.append(term)
    return tuple(hits)


def _scope_of(folded: str, *, sites: tuple[str, ...],
              source: str, destination: str, devices: tuple[str, ...],
              interfaces: tuple[str, ...]) -> tuple[str, list[str]]:
    """(scope, basis). Enterprise phrasing is a POSITIVE scope."""

    for term in ENTERPRISE_SCOPE_TERMS:
        if term in folded:
            return SCOPE_ENTERPRISE, [
                f"scope enterprise: the question says “{term}”"
            ]
    if sites:
        return SCOPE_SITES, [
            "scope sites: the question names " + ", ".join(sites)
        ]
    if source or destination or devices:
        named = [item for item in (source, destination) if item]
        named += list(devices)
        return SCOPE_DEVICES, [
            "scope devices: the question names " + ", ".join(named)
        ]
    if interfaces:
        return SCOPE_INTERFACES, [
            "scope interfaces: the question names " + ", ".join(interfaces)
        ]
    return "", []


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

    # -- PR-171: subject, objective and positive scope ---------------
    # Protocols first — "ospf configuration" is about OSPF, not about
    # configuration in general; the domain subject only stands in when
    # no protocol claimed the question.
    protocol = _match_vocabulary(folded, PROTOCOLS)
    basis: list[str] = []
    subject = protocol
    if subject:
        basis.append(f"subject {subject}: protocol recognised")
    else:
        subject = _match_vocabulary(folded, DOMAIN_SUBJECTS)
        if subject:
            basis.append(f"subject {subject}: terminology recognised")

    objective, objective_basis = _objective(
        folded, has_subject=bool(subject),
    )
    basis.extend(objective_basis)

    scope, scope_basis = _scope_of(
        folded, sites=tuple(sites), source=source, destination=destination,
        devices=(), interfaces=interfaces,
    )
    basis.extend(scope_basis)
    # A validation question that names no place is asking about the
    # whole estate — the honest default for "is all the X configuration
    # fine", and a POSITIVE value, never a fallback the operator cannot
    # see.
    if not scope and objective == OBJECTIVE_VALIDATE:
        scope = SCOPE_ENTERPRISE
        basis.append(
            "scope enterprise: a validation naming no narrower place "
            "is judged estate-wide"
        )

    return InvestigationRequest(
        question=text.strip(),
        subject=subject,
        objective=objective,
        scope=scope,
        basis=tuple(basis),
        protocol=protocol,
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
        temporal_terms=_match_all_terms(folded, TEMPORAL_TERMS),
    )
