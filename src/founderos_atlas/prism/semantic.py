"""Semantic redaction: preserve meaning, protect identity (PR-166.2).

Blind redaction protects an identifier by destroying it:

    Atlas found no BGP peering between [redacted:hostname-2] and
    [redacted:hostname-1].

Secure, and useless — the operator cannot tell which devices are being
discussed. Semantic redaction replaces the identifier with a
*meaningful* alias built from metadata Atlas already holds:

    Atlas found no BGP peering between the Mumbai Core Router and the
    Hyderabad Border Firewall.

Three rules govern this module, in order of precedence:

1. **Never invent metadata.** An alias is assembled only from facts
   Atlas has: the device's assigned site, its platform/vendor, and
   role words present in its own hostname. When Atlas knows nothing,
   the alias degrades to "Device 1" rather than inventing a role.
2. **Never weaken the secret rules.** Credentials, keys, SNMP
   communities and tokens are removed under every profile. No profile
   can preserve them; there is no field for that.
3. **Aliases are stable.** One device has one alias for the life of a
   request, so "the Mumbai Core Router" is the same machine every time
   it appears.

The alias map itself is a SERVER-SIDE artifact. The provider receives
only alias text; the operator's page maps aliases back to real Atlas
objects through the existing RBAC. What Atlas stores, what the provider
receives and what the operator sees are three different things, and
this module is where they are kept apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


# -- per-field actions ------------------------------------------------------

PRESERVE = "preserve"
ALIAS = "alias"
MASK = "mask"
REMOVE = "remove"

ACTIONS = (PRESERVE, ALIAS, MASK, REMOVE)
ACTION_LABELS = {
    PRESERVE: "Preserve",
    ALIAS: "Semantic alias",
    MASK: "Mask",
    REMOVE: "Remove",
}

# Fields an administrator can govern. Secrets are deliberately NOT
# here: they are removed always, by rules no profile can reach.
FIELD_HOSTNAMES = "hostnames"
FIELD_DEVICE_NAMES = "device_names"
FIELD_SITE_NAMES = "site_names"
FIELD_IP_ADDRESSES = "ip_addresses"
FIELD_MAC_ADDRESSES = "mac_addresses"
FIELD_VRFS = "vrfs"
FIELD_VLANS = "vlans"
FIELD_USERNAMES = "usernames"
FIELD_APPLICATIONS = "application_names"
FIELD_SERIALS = "serial_numbers"
FIELD_PLATFORMS = "platform_names"

FIELDS: tuple[tuple[str, str], ...] = (
    (FIELD_HOSTNAMES, "Hostnames"),
    (FIELD_DEVICE_NAMES, "Device names"),
    (FIELD_SITE_NAMES, "Site names"),
    (FIELD_IP_ADDRESSES, "IP addresses"),
    (FIELD_MAC_ADDRESSES, "MAC addresses"),
    (FIELD_VRFS, "VRFs"),
    (FIELD_VLANS, "VLANs"),
    (FIELD_USERNAMES, "Usernames"),
    (FIELD_APPLICATIONS, "Application names"),
    (FIELD_SERIALS, "Serial numbers"),
    (FIELD_PLATFORMS, "Platform names"),
)
FIELD_LABELS = dict(FIELDS)

# The fields that identify the estate itself. Preserving one of these
# on a third-party provider is a decision worth warning about;
# preserving a VLAN id or an application name is not, and warning about
# it on every save would train administrators to ignore the warning.
IDENTIFYING_FIELDS: tuple[str, ...] = (
    FIELD_HOSTNAMES, FIELD_DEVICE_NAMES, FIELD_IP_ADDRESSES,
    FIELD_MAC_ADDRESSES, FIELD_USERNAMES, FIELD_SERIALS,
)


# -- privacy profiles -------------------------------------------------------

# Governed fields that map onto an existing optional redaction rule.
# A field with no rule here is still governed for ALIAS purposes (the
# alias book applies it), but there is no generic pattern that can find
# it in free text — Atlas will not guess at a VRF name in prose.
POLICY_RULES: dict[str, str] = {
    FIELD_HOSTNAMES: "hostnames",
    FIELD_DEVICE_NAMES: "hostnames",
    FIELD_IP_ADDRESSES: "ip-addresses",
    FIELD_MAC_ADDRESSES: "mac-addresses",
    FIELD_USERNAMES: "usernames",
}


@dataclass(frozen=True)
class PrivacyProfile:
    """One named privacy posture: an action per field."""

    key: str
    label: str
    description: str
    rules: dict[str, str]
    hosting: str = "any"          # any | local | cloud — advisory

    def action(self, field_name: str) -> str:
        return self.rules.get(field_name, ALIAS)

    def preserves(self, field_name: str) -> bool:
        return self.action(field_name) == PRESERVE

    def optional_rules(self) -> tuple[str, ...]:
        """The optional redaction rules this profile turns on.

        A field set to Preserve turns its rule OFF, which is how the
        Internal profile keeps hostnames and addresses intact for a
        model running on your own network.
        """

        enabled: list[str] = []
        for field_name, rule in POLICY_RULES.items():
            if not self.preserves(field_name) and rule not in enabled:
                enabled.append(rule)
        return tuple(enabled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label,
            "description": self.description, "hosting": self.hosting,
            "rules": {name: self.action(name) for name, _ in FIELDS},
        }

    def with_overrides(self, overrides: dict[str, str]) -> "PrivacyProfile":
        """A copy with per-field administrator overrides applied
        (Part 7). Unknown fields and unknown actions are ignored rather
        than silently changing the posture to something unintended."""

        rules = dict(self.rules)
        for field_name, action in (overrides or {}).items():
            if field_name in FIELD_LABELS and action in ACTIONS:
                rules[field_name] = action
        if rules == self.rules:
            return self
        return PrivacyProfile(
            key=self.key, label=self.label, description=self.description,
            rules=rules, hosting=self.hosting,
        )


PROFILE_INTERNAL = "internal"
PROFILE_CLOUD = "cloud"
PROFILE_HIGH_SECURITY = "high-security"

PROFILES: tuple[PrivacyProfile, ...] = (
    PrivacyProfile(
        key=PROFILE_INTERNAL, label="Internal (trusted local model)",
        hosting="local",
        description=(
            "For a model running inside your own network. Hostnames, "
            "addresses and site names are preserved, because the data "
            "never leaves the organisation. Credentials and key "
            "material are still removed — always."
        ),
        rules={
            FIELD_HOSTNAMES: PRESERVE, FIELD_DEVICE_NAMES: PRESERVE,
            FIELD_SITE_NAMES: PRESERVE, FIELD_IP_ADDRESSES: PRESERVE,
            FIELD_MAC_ADDRESSES: PRESERVE, FIELD_VRFS: PRESERVE,
            FIELD_VLANS: PRESERVE, FIELD_USERNAMES: MASK,
            FIELD_APPLICATIONS: PRESERVE, FIELD_SERIALS: MASK,
            FIELD_PLATFORMS: PRESERVE,
        },
    ),
    PrivacyProfile(
        key=PROFILE_CLOUD, label="Cloud (default)", hosting="cloud",
        description=(
            "For an external provider. Infrastructure identifiers "
            "become meaningful aliases — “Mumbai Core Router” rather "
            "than your real hostname — so the explanation stays useful "
            "while your naming conventions stay private. Site names "
            "are preserved because they carry the operational meaning; "
            "addresses are masked."
        ),
        rules={
            FIELD_HOSTNAMES: ALIAS, FIELD_DEVICE_NAMES: ALIAS,
            FIELD_SITE_NAMES: PRESERVE, FIELD_IP_ADDRESSES: MASK,
            FIELD_MAC_ADDRESSES: MASK, FIELD_VRFS: ALIAS,
            FIELD_VLANS: PRESERVE, FIELD_USERNAMES: REMOVE,
            FIELD_APPLICATIONS: PRESERVE, FIELD_SERIALS: REMOVE,
            FIELD_PLATFORMS: PRESERVE,
        },
    ),
    PrivacyProfile(
        key=PROFILE_HIGH_SECURITY, label="High security", hosting="cloud",
        description=(
            "Everything identifying becomes an alias, including site "
            "names and addresses. The explanation still describes roles "
            "and relationships, so it remains readable, but nothing in "
            "it names your estate."
        ),
        rules={
            FIELD_HOSTNAMES: ALIAS, FIELD_DEVICE_NAMES: ALIAS,
            FIELD_SITE_NAMES: ALIAS, FIELD_IP_ADDRESSES: ALIAS,
            FIELD_MAC_ADDRESSES: ALIAS, FIELD_VRFS: ALIAS,
            FIELD_VLANS: ALIAS, FIELD_USERNAMES: ALIAS,
            FIELD_APPLICATIONS: ALIAS, FIELD_SERIALS: REMOVE,
            FIELD_PLATFORMS: ALIAS,
        },
    ),
)
PROFILE_BY_KEY = {profile.key: profile for profile in PROFILES}
DEFAULT_PROFILE = PROFILE_CLOUD

# "Match the provider": a trusted local model gets Internal, an
# external one gets Cloud. The default, because it is the choice an
# administrator would make anyway.
PROFILE_AUTO = "auto"


def profile(key: str) -> PrivacyProfile:
    return PROFILE_BY_KEY.get(str(key or ""), PROFILE_BY_KEY[DEFAULT_PROFILE])


def legacy_profile(rules: Iterable[str]) -> PrivacyProfile:
    """Describe a pre-PR-166.2 configuration as a profile.

    Before semantic redaction there were four on/off rules and every
    replacement was an opaque placeholder — which is exactly "mask".
    Rendering an existing configuration this way means an administrator
    who has not yet chosen a profile still sees an accurate account of
    what is happening, rather than a profile that was assumed for them.
    """

    enabled = {str(rule) for rule in rules or ()}
    mapped = {
        field_name: (MASK if POLICY_RULES.get(field_name) in enabled
                     else PRESERVE)
        for field_name, _ in FIELDS
    }
    # Fields with no generic pattern were never redacted before.
    for field_name, _ in FIELDS:
        if field_name not in POLICY_RULES:
            mapped[field_name] = PRESERVE
    return PrivacyProfile(
        key="legacy", label="Custom (rules configured before profiles)",
        hosting="any",
        description=(
            "This enterprise configured individual redaction rules "
            "before privacy profiles existed. Those rules are still in "
            "force and are shown above as the equivalent per-field "
            "policy. Choosing a profile replaces them."
        ),
        rules=mapped,
    )


def profile_for_hosting(hosting: str) -> str:
    """The profile a provider defaults to (Parts 8 and 9): a trusted
    local model gets Internal, anything external gets Cloud."""

    return PROFILE_INTERNAL if hosting == "local" else PROFILE_CLOUD


# -- alias construction -----------------------------------------------------

# Role words Atlas may find IN A HOSTNAME. Reading a device's own name
# is not invention; guessing a role Atlas has no sign of would be.
ROLE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Core", ("core",)),
    ("Edge", ("edge",)),
    ("Border", ("border",)),
    ("Distribution", ("dist", "distribution")),
    ("Access", ("access", "acc")),
    ("Branch", ("branch",)),
    ("Regional", ("regional", "region")),
    ("WAN", ("wan",)),
    ("Data Centre", ("dc", "datacentre", "datacenter")),
    ("Management", ("mgmt", "management", "oob")),
    ("Spine", ("spine",)),
    ("Leaf", ("leaf",)),
)

# Device-kind words, from the hostname or the platform.
KIND_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Firewall", ("fw", "firewall", "asa", "palo", "fortigate", "srx")),
    ("Switch", ("sw", "switch", "cat", "nexus")),
    ("Router", ("rtr", "router", "isr", "asr", "mx")),
    ("Load Balancer", ("lb", "f5", "bigip")),
    ("Access Point", ("ap", "wlc")),
    ("Server", ("srv", "server")),
    ("Client", ("client", "host", "pc")),
)

_TOKENS = re.compile(r"[^a-z0-9]+")


def _tokens(value: str) -> list[str]:
    return [item for item in _TOKENS.split(str(value or "").casefold())
            if item]


def _title(value: str) -> str:
    text = str(value or "").strip().replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() if part.islower() else part
                    for part in text.split())


def _match_words(tokens: Iterable[str],
                 vocabulary: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    token_set = set(tokens)
    for label, words in vocabulary:
        if token_set & set(words):
            return label
    return ""


_ROLE_TOKENS = {word for _, words in ROLE_WORDS for word in words}
_KIND_TOKENS = {word for _, words in KIND_WORDS for word in words}

# Atlas's OWN role classification, which is deterministic and
# evidence-based ("Hostnames are never evidence" — platforms/classify).
# Preferred over anything read out of a name, because it is a fact
# Atlas established rather than a reading of a naming convention.
CLASSIFIED_KINDS = {
    "router": "Router",
    "layer2_switch": "Switch",
    "layer3_switch": "Layer 3 Switch",
    "firewall": "Firewall",
    "wireless_access_point": "Access Point",
    "server": "Server",
    "linux_host": "Linux Host",
    "load_balancer": "Load Balancer",
    "cloud": "Cloud Gateway",
}


def classified_kind(device, *, metadata: dict | None = None,
                    interfaces: Iterable[Any] = ()) -> tuple[str, str]:
    """(kind, evidence) from Atlas's own role classifier, or ("", "").

    The classifier needs a snapshot-shaped mapping, which is assembled
    here from the enterprise device. Failure is silent and total: an
    unclassifiable device simply gets no kind, and the alias falls back
    to what the hostname and platform say.
    """

    try:
        from founderos_atlas.platforms.classify import classify_role
    except Exception:                       # pragma: no cover - defensive
        return "", ""

    payload = {
        "hostname": getattr(device, "hostname", ""),
        "vendor": getattr(device, "vendor", "") or "",
        "platform": getattr(device, "platform", "") or "",
        "os_name": getattr(device, "os_version", "") or "",
        "interfaces": [
            {"name": getattr(item, "name", ""),
             "ip_address": getattr(item, "ip_address", "")}
            for item in (interfaces or ())
        ],
        "metadata": dict(metadata or {}),
    }
    try:
        role, evidence = classify_role(payload)
    except Exception:                       # pragma: no cover - defensive
        return "", ""
    kind = CLASSIFIED_KINDS.get(str(role or ""), "")
    return (kind, str(evidence or "")) if kind else ("", "")


def _match_prefix(tokens: Iterable[str],
                  vocabulary: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    """Match a vocabulary word as the PREFIX of a token.

    Platform strings arrive as one run of letters and digits — ISR4451,
    ASA5525, C9300 — so exact token matching finds nothing. A prefix
    match reads ISR4451 as a router and ASA5525 as a firewall, which is
    what the platform string actually says.
    """

    for token in tokens:
        for label, words in vocabulary:
            for word in words:
                if len(word) >= 2 and token.startswith(word):
                    return label
    return ""


def device_site_name(device) -> tuple[str, str]:
    """The site Atlas associates with a device, and the basis for it.

    Returns ("", "") when Atlas knows of no site — an alias will then
    describe the device without a location rather than invent one.
    """

    assignment = getattr(device, "site", None)
    label = str(getattr(assignment, "label", "") or "").strip()
    if label and label not in ("unknown", "ambiguous"):
        return label, "assigned site"

    # No assigned site. Many estates encode location in the hostname
    # (chennai-regional-edge), and reading the device's own name is not
    # invention — but it is a weaker basis, so it is labelled as one,
    # exactly as the investigator labels its hostname grouping.
    tokens = _tokens(getattr(device, "hostname", ""))
    for token in tokens:
        if token in _ROLE_TOKENS or token in _KIND_TOKENS:
            continue
        if token.isalpha() and len(token) > 2:
            return token, "location in the hostname, not an assigned site"
        break
    return "", ""


def describe_device(device, *, site_label: str = "",
                    site_basis: str = "", platform: str = "",
                    kind_override: str = "", kind_basis: str = "") -> tuple[
                        str, list[str]]:
    """A human description of one device, and the facts it came from.

    Returns e.g. ("Mumbai Core Router", ["assigned site", "role word in
    the hostname", "platform"]). Everything in the description comes
    from Atlas's own data; when nothing is derivable the caller falls
    back to a numbered generic rather than inventing a role.

    ``site_label`` is passed in rather than read here, because under a
    profile that aliases site names the caller substitutes the SITE'S
    OWN ALIAS — otherwise a device alias of "Mumbai Core Router" would
    leak the very site name the profile just protected.
    """

    tokens = _tokens(getattr(device, "hostname", ""))
    basis: list[str] = []

    site = str(site_label or "").strip()
    if site and site_basis:
        basis.append(site_basis)

    role = _match_words(tokens, ROLE_WORDS)
    if role:
        basis.append("role word in the hostname")

    # Atlas's own classification first — it is evidence, not a reading
    # of a name. Only when Atlas could not classify the device does the
    # alias fall back to the hostname and the platform string.
    if kind_override:
        kind = kind_override
        basis.append(kind_basis or "Atlas device role classification")
    elif (kind := _match_words(tokens, KIND_WORDS)):
        basis.append("device-kind word in the hostname")
    else:
        platform_tokens = _tokens(platform or getattr(device, "platform", ""))
        kind = (_match_words(platform_tokens, KIND_WORDS)
                or _match_prefix(platform_tokens, KIND_WORDS))
        if kind:
            basis.append("platform")

    parts = [_title(site), role, kind]
    description = " ".join(part for part in parts if part).strip()
    return description, basis


@dataclass(frozen=True)
class SemanticAlias:
    """One alias, and everything needed to explain and undo it."""

    alias: str
    original: str
    kind: str                    # device | site | address | value
    action: str                  # alias | mask | remove | preserve
    field: str                   # which governed field produced it
    basis: tuple[str, ...] = ()  # the Atlas facts the alias was built from
    object_id: str = ""          # Atlas object, for an authorised operator
    href: str = ""

    def to_dict(self, *, include_original: bool) -> dict[str, Any]:
        """The operator-facing form. ``include_original`` is decided by
        the CALLER from the authenticated user's permissions — this
        object never decides who may see a real name."""

        payload = {
            "alias": self.alias, "kind": self.kind, "action": self.action,
            "field": self.field, "basis": list(self.basis),
            "object_id": self.object_id, "href": self.href,
        }
        if include_original:
            payload["original"] = self.original
        return payload


class AliasBook:
    """Stable aliases for one request.

    The same original always maps to the same alias, and two different
    originals never share one. Built once per explanation and held
    server-side: the provider sees alias text only, and the operator's
    page uses this to map back.
    """

    def __init__(self, active_profile: PrivacyProfile | None = None) -> None:
        self.profile = active_profile or profile(DEFAULT_PROFILE)
        self._by_original: dict[str, SemanticAlias] = {}
        self._used_aliases: dict[str, str] = {}   # alias -> original
        self._counters: dict[str, int] = {}

    # -- construction ------------------------------------------------

    def _unique(self, base: str, fallback_kind: str) -> str:
        """Make ``base`` unique. Two Mumbai core routers become
        "Mumbai Core Router" and "Mumbai Core Router 2" — never the
        same alias for two machines."""

        candidate = base or _title(fallback_kind)
        if candidate not in self._used_aliases:
            return candidate
        index = 2
        while f"{candidate} {index}" in self._used_aliases:
            index += 1
        return f"{candidate} {index}"

    def _next_generic(self, kind: str) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return f"{_title(kind)} {self._counters[kind]}"

    def _release(self, entry: "SemanticAlias") -> None:
        """Withdraw an entry that is being replaced by a stronger one."""

        self._by_original.pop(entry.original.casefold(), None)
        if self._used_aliases.get(entry.alias) == entry.original:
            del self._used_aliases[entry.alias]

    def add(self, original: str, *, kind: str, field_name: str,
            description: str = "", basis: Iterable[str] = (),
            object_id: str = "", href: str = "") -> SemanticAlias:
        key = str(original or "").casefold()
        action = self.profile.action(field_name)
        existing = self._by_original.get(key)
        if existing is not None:
            # One value, two roles. A device whose hostname is also a
            # site name (a site called "mumbai" with a device called
            # "mumbai") arrived here twice, and returning the earlier
            # SITE entry meant the device never got one: under Cloud the
            # site is Preserve, so the real hostname went to the
            # provider verbatim AND known_names_for() then dropped it
            # from the generic rules as "preserved". A leak, and a
            # regression against the blind redaction it replaced.
            #
            # Protection wins over preservation, always.
            if existing.action != PRESERVE or action == PRESERVE:
                return existing
            self._release(existing)
        if action == ALIAS:
            base = description.strip()
            # AN ALIAS MUST NEVER CONTAIN THE VALUE IT PROTECTS. A
            # device whose hostname is also its site name built the
            # alias "Mumbai Router" out of the site — disclosing the
            # hostname it was replacing. When the two promises collide
            # (protect this hostname, preserve that site name), the
            # protection wins and the alias goes generic.
            if base and str(original).casefold() in base.casefold():
                base = ""
            alias = (self._unique(base, kind) if base
                     else self._next_generic(kind))
        elif action == MASK:
            alias = self._next_generic(kind)
        elif action == REMOVE:
            alias = f"[removed:{kind}]"
        else:
            alias = str(original)
        entry = SemanticAlias(
            alias=alias, original=str(original), kind=kind, action=action,
            field=field_name, basis=tuple(basis), object_id=object_id,
            href=href,
        )
        self._by_original[key] = entry
        if action != PRESERVE:
            self._used_aliases[alias] = str(original)
        return entry

    # -- reads -------------------------------------------------------

    def for_original(self, original: str) -> SemanticAlias | None:
        return self._by_original.get(str(original or "").casefold())

    def entries(self) -> tuple[SemanticAlias, ...]:
        return tuple(self._by_original.values())

    def originals(self) -> tuple[str, ...]:
        """Every original value, longest first — so a replacement pass
        rewrites "mumbai-core-01" before the shorter "mumbai"."""

        return tuple(sorted(
            (entry.original for entry in self._by_original.values()),
            key=len, reverse=True,
        ))

    def counts(self) -> dict[str, int]:
        totals = {ALIAS: 0, MASK: 0, REMOVE: 0, PRESERVE: 0}
        for entry in self._by_original.values():
            totals[entry.action] = totals.get(entry.action, 0) + 1
        return totals

    def summary(self) -> str:
        counts = self.counts()
        parts = [
            f"{counts[action]} {ACTION_LABELS[action].lower()}"
            for action in (ALIAS, MASK, REMOVE)
            if counts.get(action)
        ]
        return ", ".join(parts) or "nothing needed an alias"


def known_names_for(book: "AliasBook", names: Iterable[str]) -> list[str]:
    """Reconcile a caller's known-name list with the alias book.

    Two rules, and the first one is the reason this exists: a name the
    profile PRESERVES is dropped, or the generic hostname rule would
    mask the very value the profile just chose to keep — the Cloud
    profile promises site names survive, and without this the payload
    said ``site: [redacted:hostname-2]``. Everything the book protects
    is then added, as a safety net for any spelling the alias pass did
    not catch.
    """

    preserved = {
        entry.original.casefold() for entry in book.entries()
        if entry.action == PRESERVE
    }
    kept: list[str] = []
    seen: set[str] = set()
    for name in list(names) + [
        entry.original for entry in book.entries()
        if entry.action != PRESERVE
    ]:
        text = str(name).strip()
        folded = text.casefold()
        if not text or folded in preserved or folded in seen:
            continue
        seen.add(folded)
        kept.append(text)
    return kept


def _interfaces_by_device(graph) -> dict[str, tuple[Any, ...]]:
    """The graph's merged interfaces, keyed by enterprise id.

    Only used to let Atlas's role classifier see routed SVIs, which is
    how it tells a layer-3 switch from a layer-2 one.
    """

    interfaces = getattr(graph, "interfaces", None)
    if isinstance(interfaces, dict):
        return {str(key): tuple(value or ()) for key, value in interfaces.items()}
    return {}


def build_alias_book(graph, *, active_profile: PrivacyProfile,
                     device_ids: Iterable[str] = ()) -> AliasBook:
    """Aliases for the devices and sites Atlas has discovered.

    ``device_ids`` narrows the book to an investigation's scope; empty
    means every discovered device. Only devices Atlas actually holds
    are aliased — an alias is never minted for a name Atlas does not
    know, because there would be no metadata to build it from.
    """

    book = AliasBook(active_profile)
    wanted = {str(item) for item in device_ids}
    in_scope = [
        device for device in (getattr(graph, "devices", ()) or ())
        if str(getattr(device, "hostname", "") or "")
        and (not wanted
             or str(getattr(device, "enterprise_id", "") or "") in wanted)
    ]

    # Sites first. A device alias may quote its site, so the site's own
    # alias has to exist before any device is described.
    site_text: dict[str, tuple[str, str]] = {}
    for device in in_scope:
        name, basis = device_site_name(device)
        if not name or name.casefold() in site_text:
            continue
        entry = book.add(
            name, kind="site", field_name=FIELD_SITE_NAMES,
            # No description: a site's only metadata IS its name, so
            # there is nothing to build a *different* meaningful alias
            # from. Under Alias it becomes "Site 1" — which still keeps
            # the relationship (two devices at Site 1 are co-located)
            # without disclosing where that is.
            description="", basis=(basis,) if basis else (),
            object_id=name, href="/topology",
        )
        site_text[name.casefold()] = (entry.alias, basis)

    metadata_by_id = dict(
        (getattr(graph, "attributes", {}) or {}).get("device_metadata", {})
        or {}
    )
    interfaces_by_id = _interfaces_by_device(graph)

    for device in in_scope:
        device_id = str(getattr(device, "enterprise_id", "") or "")
        hostname = str(getattr(device, "hostname", "") or "")
        name, basis = device_site_name(device)
        label, site_basis = site_text.get(name.casefold(), ("", ""))
        kind, kind_basis = classified_kind(
            device, metadata=metadata_by_id.get(device_id),
            interfaces=interfaces_by_id.get(device_id, ()),
        )
        description, facts = describe_device(
            device, site_label=label, site_basis=site_basis,
            kind_override=kind, kind_basis=kind_basis,
        )
        book.add(
            hostname, kind="device", field_name=FIELD_HOSTNAMES,
            description=description, basis=facts, object_id=device_id,
            href=f"/devices/{device_id}" if device_id else "",
        )
    return book
