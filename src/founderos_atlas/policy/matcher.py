"""Policy matcher — the fixed operator vocabulary policies are written against.

The design commitment (PR-047 Part 1): **policies are data, not code.** A policy
declares *what* to look for; this module is the small, fixed set of *how* — the
interpreter's opcodes. Adding a policy (or a whole pack) needs only data. Adding
an operator is a rare, reviewed change here. That boundary is what lets Cisco,
CIS, STIG, PCI packs (Part 6) ship as definitions with no engine change.

Operators are deliberately few and boring (no regex-DSL sprawl):

- ``any_present``          PASS if at least one pattern is found
- ``all_present``          PASS if every pattern is found (reports which are missing)
- ``none_present``         PASS if no pattern is found (prohibited configuration)
- ``conditional_present``  if any *antecedent* is present, every pattern must be —
                           otherwise Not Applicable (a device without BGP does not
                           fail a "BGP router-id" policy)
- ``interfaces_shutdown``  structural: every admin-up interface has an address or a
                           description (an unused, unconfigured, up interface fails)

Every operator is a pure function of text; determinism is total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


# -- operators (the fixed vocabulary) ----------------------------------------

OP_ANY_PRESENT = "any_present"
OP_ALL_PRESENT = "all_present"
OP_NONE_PRESENT = "none_present"
OP_CONDITIONAL_PRESENT = "conditional_present"
OP_INTERFACES_SHUTDOWN = "interfaces_shutdown"

OPERATORS = (
    OP_ANY_PRESENT,
    OP_ALL_PRESENT,
    OP_NONE_PRESENT,
    OP_CONDITIONAL_PRESENT,
    OP_INTERFACES_SHUTDOWN,
)

MATCH_SUBSTRING = "substring"
MATCH_REGEX = "regex"


@dataclass(frozen=True)
class LineHit:
    """One matched configuration line — line number (1-based) and its (masked)
    text, for the "which configuration?" explanation."""

    line: int
    text: str
    pattern: str

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "text": self.text, "pattern": self.pattern}


@dataclass(frozen=True)
class MatchReport:
    """The result of running one operator over one body of text.

    ``applicable`` is False only for ``conditional_present`` when the antecedent
    is absent — the policy simply does not apply to this device, which is a
    distinct, honest state from pass or fail.
    """

    operator: str
    matched: bool
    applicable: bool
    hits: tuple[LineHit, ...] = ()
    missing_patterns: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "matched": self.matched,
            "applicable": self.applicable,
            "hits": [h.to_dict() for h in self.hits],
            "missing_patterns": list(self.missing_patterns),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PolicyCheck:
    """The declarative "Rule" field of a policy (Part 1). Pure data."""

    evidence: str                         # evidence kind to match against
    operator: str
    patterns: tuple[str, ...] = ()
    antecedent: tuple[str, ...] = ()      # conditional_present only
    match: str = MATCH_SUBSTRING
    ignore_case: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence,
            "operator": self.operator,
            "patterns": list(self.patterns),
            "antecedent": list(self.antecedent),
            "match": self.match,
            "ignore_case": self.ignore_case,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PolicyCheck":
        return cls(
            evidence=str(value["evidence"]),
            operator=str(value["operator"]),
            patterns=tuple(value.get("patterns") or ()),
            antecedent=tuple(value.get("antecedent") or ()),
            match=str(value.get("match") or MATCH_SUBSTRING),
            ignore_case=bool(value.get("ignore_case", True)),
        )


def _find_hits(check: PolicyCheck, patterns: tuple[str, ...], text: str) -> list[LineHit]:
    """Every line matching any of ``patterns``, in file order."""

    hits: list[LineHit] = []
    lines = text.splitlines()
    flags = re.IGNORECASE if check.ignore_case else 0
    for pattern in patterns:
        if check.match == MATCH_REGEX:
            try:
                compiled = re.compile(pattern, flags)
            except re.error:
                continue
            predicate = lambda line, c=compiled: c.search(line) is not None
        else:
            needle = pattern.casefold() if check.ignore_case else pattern
            predicate = lambda line, n=needle: (
                (line.casefold() if check.ignore_case else line).find(n) != -1
            )
        for index, line in enumerate(lines, start=1):
            if predicate(line):
                hits.append(LineHit(line=index, text=line.strip(), pattern=pattern))
    return hits


def _matched_patterns(check: PolicyCheck, patterns: tuple[str, ...], text: str) -> set[str]:
    return {hit.pattern for hit in _find_hits(check, patterns, text)}


def evaluate_check(check: PolicyCheck, text: str) -> MatchReport:
    """Run one operator over one body of (masked) text. Pure and deterministic."""

    if check.operator == OP_ANY_PRESENT:
        hits = _find_hits(check, check.patterns, text)
        matched = bool(hits)
        return MatchReport(
            operator=check.operator,
            matched=matched,
            applicable=True,
            hits=tuple(hits),
            missing_patterns=() if matched else check.patterns,
            detail=(
                "found at least one required directive"
                if matched
                else "none of the required directives are present"
            ),
        )

    if check.operator == OP_ALL_PRESENT:
        found = _matched_patterns(check, check.patterns, text)
        missing = tuple(p for p in check.patterns if p not in found)
        hits = _find_hits(check, check.patterns, text)
        return MatchReport(
            operator=check.operator,
            matched=not missing,
            applicable=True,
            hits=tuple(hits),
            missing_patterns=missing,
            detail=(
                "every required directive is present"
                if not missing
                else f"missing: {', '.join(missing)}"
            ),
        )

    if check.operator == OP_NONE_PRESENT:
        hits = _find_hits(check, check.patterns, text)
        matched = not hits
        return MatchReport(
            operator=check.operator,
            matched=matched,
            applicable=True,
            hits=tuple(hits),
            missing_patterns=(),
            detail=(
                "no prohibited directive is present"
                if matched
                else "a prohibited directive is present"
            ),
        )

    if check.operator == OP_CONDITIONAL_PRESENT:
        antecedent_hits = _find_hits(check, check.antecedent, text)
        if not antecedent_hits:
            return MatchReport(
                operator=check.operator,
                matched=True,
                applicable=False,
                hits=(),
                missing_patterns=(),
                detail="not applicable — the antecedent configuration is not present",
            )
        found = _matched_patterns(check, check.patterns, text)
        missing = tuple(p for p in check.patterns if p not in found)
        hits = tuple(antecedent_hits) + tuple(_find_hits(check, check.patterns, text))
        return MatchReport(
            operator=check.operator,
            matched=not missing,
            applicable=True,
            hits=hits,
            missing_patterns=missing,
            detail=(
                "the required directive is present where it must be"
                if not missing
                else f"required but missing: {', '.join(missing)}"
            ),
        )

    if check.operator == OP_INTERFACES_SHUTDOWN:
        return _evaluate_interfaces_shutdown(check, text)

    # Unknown operator: refuse to guess a verdict.
    return MatchReport(
        operator=check.operator,
        matched=False,
        applicable=False,
        detail=f"unsupported operator {check.operator!r}",
    )


def _evaluate_interfaces_shutdown(check: PolicyCheck, text: str) -> MatchReport:
    """Every admin-up interface should have an address or a description; an
    interface that is up, unaddressed, and undescribed is an unused-but-enabled
    port. Parses interface stanzas structurally (indentation-delimited), which
    covers both IOS-style and FRR-style running-config.
    """

    lines = text.splitlines()
    offenders: list[LineHit] = []
    checked = 0
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        header = raw.strip()
        low = header.casefold()
        if low.startswith("interface ") and not raw[:1].isspace():
            name = header[len("interface "):].strip()
            # Loopbacks and management are never "unused"; skip them.
            body: list[str] = []
            j = i + 1
            while j < n:
                nxt = lines[j]
                if nxt.strip() and (nxt[:1].isspace() or nxt.strip() == "!"):
                    if nxt.strip() == "!":
                        break
                    body.append(nxt.strip())
                    j += 1
                    continue
                if not nxt.strip():
                    j += 1
                    continue
                break
            if not name.casefold().startswith(("lo", "loopback", "null", "mgmt")):
                checked += 1
                body_l = [b.casefold() for b in body]
                shutdown = any(b == "shutdown" for b in body_l)
                addressed = any(
                    b.startswith(("ip address", "ipv6 address")) and "no ip address" not in b
                    for b in body_l
                )
                described = any(b.startswith("description") for b in body_l)
                if not shutdown and not addressed and not described:
                    offenders.append(
                        LineHit(line=i + 1, text=header, pattern="unused-interface")
                    )
            i = j
            continue
        i += 1

    matched = not offenders
    if checked == 0:
        return MatchReport(
            operator=check.operator,
            matched=True,
            applicable=False,
            detail="no non-loopback interfaces found to assess",
        )
    return MatchReport(
        operator=check.operator,
        matched=matched,
        applicable=True,
        hits=tuple(offenders),
        detail=(
            "every enabled interface is addressed, described, or shut down"
            if matched
            else f"{len(offenders)} enabled interface(s) are unused and not shut down"
        ),
    )
