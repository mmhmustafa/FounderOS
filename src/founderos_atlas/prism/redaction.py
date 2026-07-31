"""PRISM privacy and redaction engine (PR-165, Part 8).

Nothing reaches a provider without passing through here. Two tiers:

MANDATORY — credentials and key material. These are redacted always,
for every provider including customer-hosted ones, and no setting can
turn them off. A secret that leaves Atlas cannot be recalled, so this
is not a policy question.

OPTIONAL — identifying detail (IP addresses, hostnames, usernames,
MAC addresses). Customers choose per policy, because a customer-hosted
model on their own network may legitimately need hostnames to be
useful, while a cloud provider may not be allowed to see them.

Every redaction is COUNTED and reported: the settings page and the
audit record state exactly what was removed, so "we redact secrets" is
an inspectable claim rather than a promise. Redacted values are
replaced by stable placeholders (``[redacted:password]``,
``[redacted:ip-1]``) — consistent within one request, so a model can
still reason about "the same device" without learning its address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Pattern


# -- policy -----------------------------------------------------------------

RULE_IP = "ip-addresses"
RULE_HOSTNAME = "hostnames"
RULE_USERNAME = "usernames"
RULE_MAC = "mac-addresses"

OPTIONAL_RULES = (RULE_IP, RULE_HOSTNAME, RULE_USERNAME, RULE_MAC)

OPTIONAL_RULE_LABELS = {
    RULE_IP: "IP addresses",
    RULE_HOSTNAME: "Hostnames",
    RULE_USERNAME: "Usernames",
    RULE_MAC: "MAC addresses",
}


@dataclass(frozen=True)
class RedactionPolicy:
    """Which optional rules apply. Mandatory rules are not represented
    here because they are not optional.

    ``known_names`` are the enterprise's real device and site names,
    supplied by the caller from Atlas's own graph. Hostname redaction
    uses them rather than guessing: a bare single-label name is
    indistinguishable from an ordinary word or a config keyword
    ("snmp-server", "read-only"), and a guessing rule mangles the very
    text it is supposed to protect. Known names plus strict dotted
    FQDNs are what Atlas can redact honestly.
    """

    optional: frozenset[str] = frozenset()
    known_names: tuple[str, ...] = ()

    @classmethod
    def from_names(
        cls, names: Iterable[str], *, known_names: Iterable[str] = ()
    ) -> "RedactionPolicy":
        return cls(
            frozenset(name for name in names if name in OPTIONAL_RULES),
            tuple(sorted(
                {str(item).strip() for item in known_names if str(item).strip()},
                key=len, reverse=True,  # longest first: FQDN before host
            )),
        )

    def with_known_names(self, names: Iterable[str]) -> "RedactionPolicy":
        return RedactionPolicy.from_names(self.optional, known_names=names)

    def enabled(self, rule: str) -> bool:
        return rule in self.optional

    def to_list(self) -> list[str]:
        return [rule for rule in OPTIONAL_RULES if rule in self.optional]


# The strictest sensible default for a feature that talks to third
# parties: identity is hidden until an administrator decides otherwise.
STRICT_POLICY = RedactionPolicy(frozenset(OPTIONAL_RULES))


# -- mandatory patterns -----------------------------------------------------
#
# Ordered: the most specific first, so "snmp community X" is labelled
# as a community rather than swallowed by the generic secret rule.
# Each entry is (label, pattern, group-to-replace). Patterns keep the
# key/prefix visible and replace only the VALUE, so the model still
# sees that a password existed — which is often the operationally
# relevant fact — without learning it.

_MANDATORY: tuple[tuple[str, Pattern[str], int], ...] = (
    # PEM key material: whole block.
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ), 0),
    # SNMP communities, both config styles.
    ("snmp-community", re.compile(
        r"(?i)\bsnmp(?:-server)?\s+community\s+(\S+)"
    ), 1),
    ("snmp-community", re.compile(
        r"(?i)\bcommunity[\s:=]+[\"']?([^\s\"',;]+)"
    ), 1),
    # Authorization headers: the scheme word (Bearer/Basic/Token) is
    # NOT the secret — the token after it is. Capturing the scheme was
    # a real leak, so the scheme is matched and skipped explicitly.
    ("api-key", re.compile(
        r"(?i)\b(?:proxy-)?authorization[\s:=]+"
        r"(?:bearer|basic|token|apikey)?\s*[\"']?([^\s\"',;]+)"
    ), 1),
    ("api-key", re.compile(
        r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{8,})"
    ), 1),
    ("api-key", re.compile(
        r"(?i)\b(?:x-api-key|api[-_]?key|apikey|access[-_]?token|"
        r"auth[-_]?token)[\s:=]+[\"']?([^\s\"',;]+)"
    ), 1),
    # Vendor-shaped keys, which often appear bare in pasted text.
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), 0),
    ("api-key", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), 0),
    ("api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), 0),
    ("api-key", re.compile(r"\bAKIA[0-9A-Z]{12,}"), 0),
    # Cisco-style config secrets.
    ("password", re.compile(
        r"(?i)\b(?:enable\s+)?(?:secret|password)\s+(?:\d\s+)?(\S+)"
    ), 1),
    ("password", re.compile(
        r"(?i)\b(?:pass(?:word|wd|phrase)?|passwd|pwd|secret|token|"
        r"credential)[\s:=]+[\"']?([^\s\"',;]+)"
    ), 1),
    # URLs carrying inline credentials.
    ("credential", re.compile(
        r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+)@"
    ), 1),
)

# Words that follow "password"/"secret" but are not secrets — redacting
# them would be noise and would hide meaning ("password required").
# Compared after stripping trailing punctuation, so "set." counts as
# "set" (it did not, once, and the sentence came back mangled).
_NOT_SECRETS = frozenset((
    "required", "missing", "invalid", "expired", "correct", "incorrect",
    "unknown", "none", "null", "empty", "set", "unset", "changed",
    "prompt", "authentication", "failed", "ok", "the", "a", "is", "was",
    "for", "to", "of", "and", "or", "not", "no", "rotation", "policy",
    # Verbs that commonly follow "token"/"password"/"secret" in prose.
    # Redacting them mangles the sentence and protects nothing.
    "used", "using", "provided", "supplied", "stored", "configured",
    "rotated", "expires", "accepted", "rejected", "matched", "sent",
    "reused", "shown", "hidden", "here", "above", "below", "verified",
))

# A lone 1-2 digit token after "secret"/"password" is a Cisco hash-type
# indicator ("enable secret 5 $1$..."), not the secret itself — the
# hash that follows is caught by the same rule.
_HASH_TYPE = re.compile(r"^\d{1,2}$")


# -- optional patterns ------------------------------------------------------

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
_IPV6 = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b")
_MAC = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"
    r"|\b(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}\b"
)
_USERNAME = re.compile(
    r"(?i)\b(?:user(?:name)?|login|operator|account)[\s:=]+[\"']?"
    r"([A-Za-z0-9._\\@-]{2,})"
)
# A dotted, TLD-shaped name: every label alphanumeric, the LAST label
# alphabetic. "mumbai-core.example.net" matches; "10.20.30.40" does
# not (numeric last label), nor does "device." (trailing punctuation is
# outside the match), nor "snmp-server" (no dot — those are covered by
# the enterprise's known names instead of guessed at).
_FQDN = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\.)+[a-z]{2,24}\b",
    re.IGNORECASE,
)
# Placeholders already inserted by an earlier rule are never re-scanned:
# without this, "[redacted:password-1]" reads as a hostname.
_PLACEHOLDER = re.compile(r"\[redacted:[a-z-]+-\d+\]")


@dataclass
class RedactionReport:
    """What was removed, by rule. Displayed and audited — never the
    values themselves, only the labels and counts."""

    counts: dict[str, int] = field(default_factory=dict)

    def add(self, label: str, amount: int = 1) -> None:
        if amount:
            self.counts[label] = self.counts.get(label, 0) + amount

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_rule": dict(sorted(self.counts.items())),
        }

    def describe(self) -> str:
        if not self.counts:
            return "nothing needed redaction"
        parts = [
            f"{count} {label}" for label, count in sorted(self.counts.items())
        ]
        return ", ".join(parts)


class _Placeholders:
    """Stable per-request placeholders: the same value always maps to
    the same token within one redaction pass, so relationships survive
    while the values do not."""

    def __init__(self) -> None:
        self._assigned: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def token(self, label: str, value: str) -> str:
        key = (label, value)
        existing = self._assigned.get(key)
        if existing:
            return existing
        index = self._counts.get(label, 0) + 1
        self._counts[label] = index
        token = f"[redacted:{label}-{index}]"
        self._assigned[key] = token
        return token


def _outside_placeholders(text: str, transform) -> str:
    """Apply ``transform`` only to the parts of ``text`` that are not
    already redaction placeholders — so no rule can redact another
    rule's output into nonsense like ``[redacted:[redacted:...]]``."""

    pieces: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER.finditer(text):
        pieces.append(transform(text[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(transform(text[cursor:]))
    return "".join(pieces)


def _redact_pattern(
    text: str, label: str, pattern: Pattern[str], group: int,
    report: RedactionReport, placeholders: _Placeholders,
    *, skip_values: frozenset[str] = frozenset(),
) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(group)
        if not value:
            return match.group(0)
        # Trailing sentence punctuation is not part of a secret.
        bare = value.rstrip(".,;:!?)\"'").casefold()
        if bare in skip_values or not bare:
            return match.group(0)
        if skip_values and _HASH_TYPE.match(bare):
            return match.group(0)
        if value.startswith("[redacted:"):
            return match.group(0)
        report.add(label)
        token = placeholders.token(label, value)
        whole = match.group(0)
        if group == 0:
            return token
        start, end = match.span(group)
        offset = match.start()
        return whole[: start - offset] + token + whole[end - offset:]

    return pattern.sub(replace, text)


def redact(
    text: str, policy: RedactionPolicy | None = None
) -> tuple[str, RedactionReport]:
    """Scrub one piece of text. Returns the safe text and the report.

    Mandatory rules always run. Optional rules run only where the
    policy enables them. Returns a report even when nothing matched,
    so callers can always state what happened.
    """

    policy = policy or STRICT_POLICY
    report = RedactionReport()
    placeholders = _Placeholders()
    safe = str(text or "")

    for label, pattern, group in _MANDATORY:
        skip = _NOT_SECRETS if label == "password" else frozenset()
        safe = _redact_pattern(
            safe, label, pattern, group, report, placeholders,
            skip_values=skip,
        )

    # Optional rules never rewrite an existing placeholder.
    def optional_pass(chunk: str) -> str:
        if policy.enabled(RULE_HOSTNAME):
            # Dotted FQDNs first, so "mumbai-core.example.net" redacts
            # as ONE name rather than splitting around its short form;
            # then the enterprise's known bare names.
            chunk = _redact_pattern(
                chunk, "hostname", _FQDN, 0, report, placeholders
            )
            for name in policy.known_names:
                pattern = re.compile(
                    rf"(?<![\w.-]){re.escape(name)}(?![\w-])", re.IGNORECASE
                )
                chunk = _redact_pattern(
                    chunk, "hostname", pattern, 0, report, placeholders
                )
        if policy.enabled(RULE_USERNAME):
            chunk = _redact_pattern(
                chunk, "username", _USERNAME, 1, report, placeholders
            )
        if policy.enabled(RULE_MAC):
            chunk = _redact_pattern(
                chunk, "mac", _MAC, 0, report, placeholders
            )
        if policy.enabled(RULE_IP):
            chunk = _redact_pattern(
                chunk, "ip", _IPV4, 0, report, placeholders
            )
            chunk = _redact_pattern(
                chunk, "ip", _IPV6, 0, report, placeholders
            )
        return chunk

    safe = _outside_placeholders(safe, optional_pass)
    return safe, report


def redact_all(
    values: Iterable[str], policy: RedactionPolicy | None = None
) -> tuple[list[str], RedactionReport]:
    """Redact several strings under one shared report. Placeholders are
    per-string; the report aggregates."""

    combined = RedactionReport()
    safe_values: list[str] = []
    for value in values:
        safe, report = redact(value, policy)
        safe_values.append(safe)
        for label, count in report.counts.items():
            combined.add(label, count)
    return safe_values, combined
