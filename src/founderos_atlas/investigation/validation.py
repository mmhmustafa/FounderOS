"""The validation capability registry (PR-172).

**Discovered, never declared.** A validation capability exists exactly
when the active policy pack installs at least one rule the subject's
declared ``policy_tags`` select. There is no hand-maintained list to
drift out of step with the pack, and therefore no way for Atlas to
advertise a validation it cannot perform (review R3): install a pack
and capability grows; remove one and it shrinks — no code change
either way.

This module is pure functions over two registries that already exist —
:data:`~founderos_atlas.investigation.subjects.SUBJECTS` and the
installed :class:`~founderos_atlas.policy.models.PolicyPack` — plus the
one dataclass that names the join. It performs no I/O, holds no state,
and never touches the policy engine itself.

``unrealised()`` is the honesty valve: a subject declaring tags that
select nothing in the active pack is a registry/pack disagreement,
reported as a diagnostic rather than silently absent — and never a
crash, because an uninstalled pack is a fact, not an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .subjects import SUBJECTS, SubjectDescriptor


# -- the masked-secret guard (PR-172, review R9 / §1.5) -----------------------
#
# Policies match MASKED configuration text: any line containing a
# sensitive term is replaced wholesale by "<masked: line contains
# '...'>" before the matcher ever sees it. A rule whose pattern
# contains one of those terms is therefore BLIND — its target line
# cannot exist in the text it searches — and it mis-judges silently:
# an any_present rule fails compliant devices; a none_present rule
# passes violating ones. The guard refuses such rules a place in any
# validation verdict, and names them, loudly, as diagnostics.
#
# One source of truth: the term list is the masker's own.

from founderos_atlas.config_intelligence.diff import SENSITIVE_TERMS

_MASKED_TERM_PATTERN = re.compile(
    r"\b(" + "|".join(SENSITIVE_TERMS) + r")\b", re.IGNORECASE
)


def mask_blind_reason(policy) -> str | None:
    """Why this rule cannot see its target in masked text, or None.

    Scoped to running-config evidence — that is the view the masker
    rewrites. Both the patterns and the antecedent are checked: a
    blind antecedent makes a conditional rule silently not-applicable
    everywhere, which is just as wrong as a blind pattern.
    """

    check = getattr(policy, "check", None)
    if check is None or getattr(check, "evidence", "") != "running-config":
        return None
    for field_name in ("patterns", "antecedent"):
        for pattern in getattr(check, field_name, ()) or ():
            match = _MASKED_TERM_PATTERN.search(str(pattern))
            if match:
                return (
                    f"pattern {str(pattern)!r} contains the sensitive "
                    f"term '{match.group(1).lower()}' — configuration "
                    "lines carrying that term are masked before "
                    "matching, so this rule can never see its target "
                    "and would judge wrongly"
                )
    return None


def mask_blind_rules(pack=None) -> tuple[tuple[str, str], ...]:
    """Every rule in the pack the masked view blinds — (policy_id,
    reason) diagnostics, for governance surfaces and tests."""

    active = _active_pack(pack)
    rows: list[tuple[str, str]] = []
    for policy in active.policies:
        reason = mask_blind_reason(policy)
        if reason:
            rows.append((policy.policy_id, reason))
    return tuple(rows)


# PR-173: the second axis. One subject, two independently discovered
# aspects — what its CONFIGURATION says, and what its operational STATE
# shows. Never merged, never averaged, never sharing a verdict word.
ASPECT_CONFIGURATION = "configuration"
ASPECT_STATE = "state"
ASPECTS = (ASPECT_CONFIGURATION, ASPECT_STATE)


@dataclass(frozen=True)
class ValidationCapability:
    """What Atlas can validate about one subject, and on what basis.

    ``rules`` and ``pack`` are provenance: every verdict built from
    this capability can name the exact rules and pack version behind
    it, which the Experience Language already requires of findings.
    ``platforms`` is the union of platform selectors across the
    selected rules — empty when at least one rule applies to every
    platform. ``aspect`` (PR-173) says which axis this capability
    judges; every PR-172 capability is ``configuration``.
    """

    subject: str                      # SubjectDescriptor.key
    label: str                        # "BGP"
    title: str                        # "BGP configuration" / "BGP sessions"
    rules: tuple[str, ...]            # the rule ids that will judge it
    pack: str                         # provenance: pack or rule-set version
    evidence_kinds: tuple[str, ...]   # evidence the rules need to judge
    platforms: tuple[str, ...]        # platforms targeted, () = all
    aspect: str = ASPECT_CONFIGURATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "label": self.label,
            "title": self.title,
            "rules": list(self.rules),
            "pack": self.pack,
            "evidence_kinds": list(self.evidence_kinds),
            "platforms": list(self.platforms),
            "aspect": self.aspect,
        }


def _active_pack(pack):
    if pack is not None:
        return pack
    from founderos_atlas.policy.packs import default_pack

    return default_pack()


def _selected_rules(descriptor: SubjectDescriptor, pack) -> tuple:
    wanted = set(descriptor.policy_tags)
    if not wanted:
        return ()
    return tuple(
        policy for policy in pack.policies
        if wanted & set(getattr(policy, "tags", ()))
        # R9: a mask-blind rule never enters a validation verdict —
        # refused HERE, at the capability seam, so no verdict can be
        # built from a rule that cannot see its own target.
        and mask_blind_reason(policy) is None
    )


def _capability_for(
    descriptor: SubjectDescriptor, pack,
) -> ValidationCapability | None:
    selected = _selected_rules(descriptor, pack)
    if not selected:
        return None
    # () = universal: if any selected rule carries no platform selector,
    # every platform can be judged by at least that rule.
    platform_patterns: set[str] = set()
    universal = False
    for policy in selected:
        patterns = tuple(
            getattr(getattr(policy, "applicability", None), "platforms", ())
        )
        if not patterns:
            universal = True
        else:
            platform_patterns.update(patterns)
    title = (
        getattr(descriptor, "validation_title", "")
        or f"{descriptor.label} configuration"
    )
    return ValidationCapability(
        subject=descriptor.key,
        label=descriptor.label,
        title=title,
        rules=tuple(policy.policy_id for policy in selected),
        pack=f"{pack.pack_id}@{pack.version}",
        evidence_kinds=tuple(sorted({
            policy.check.evidence for policy in selected
        })),
        platforms=() if universal else tuple(sorted(platform_patterns)),
    )


def _state_capability_for(
    descriptor: SubjectDescriptor,
) -> ValidationCapability | None:
    """The STATE capability, discovered exactly like configuration's:
    the subject declares an observation kind, and at least one state
    rule judges that kind. Either half missing means no capability —
    and the refusal upstream names WHICH half, because they lead to
    different actions (write a parser vs. write a rule)."""

    kind = str(getattr(descriptor, "state_kind", "") or "")
    if not kind:
        return None
    from .state_rules import STATE_RULES_VERSION, rules_for_kind

    selected = tuple(
        rule for rule in rules_for_kind(kind)
        if rule.subject == descriptor.key
    )
    if not selected:
        return None
    title = (
        getattr(descriptor, "state_title", "")
        or f"{descriptor.label} state"
    )
    return ValidationCapability(
        subject=descriptor.key,
        label=descriptor.label,
        title=title,
        rules=tuple(rule.rule_id for rule in selected),
        pack=STATE_RULES_VERSION,
        evidence_kinds=(kind,),
        platforms=(),
        aspect=ASPECT_STATE,
    )


def capabilities(
    pack=None, *, subjects: tuple[SubjectDescriptor, ...] | None = None,
    aspect: str = ASPECT_CONFIGURATION,
) -> tuple[ValidationCapability, ...]:
    """Every validation Atlas can currently perform on one aspect,
    alphabetically by label — the order an operator-facing list wants.

    ``aspect`` defaults to configuration so every PR-172 caller keeps
    its exact behaviour. ``subjects`` exists so a test (or a future
    caller) can derive over a different subject registry; production
    callers never pass it.
    """

    roster = subjects if subjects is not None else SUBJECTS
    if aspect == ASPECT_STATE:
        found = [
            item for item in (
                _state_capability_for(descriptor) for descriptor in roster
            )
            if item is not None
        ]
    else:
        active = _active_pack(pack)
        found = [
            item for item in (
                _capability_for(descriptor, active)
                for descriptor in roster
            )
            if item is not None
        ]
    found.sort(key=lambda item: item.label.casefold())
    return tuple(found)


def capability(
    subject: str, pack=None, *,
    subjects: tuple[SubjectDescriptor, ...] | None = None,
    aspect: str = ASPECT_CONFIGURATION,
) -> ValidationCapability | None:
    """The capability for one subject key and one aspect, or None —
    and None is a refusal upstream, never a silent pass."""

    key = str(subject or "")
    for descriptor in (subjects if subjects is not None else SUBJECTS):
        if descriptor.key == key:
            if aspect == ASPECT_STATE:
                return _state_capability_for(descriptor)
            return _capability_for(descriptor, _active_pack(pack))
    return None


def unrealised(
    pack=None, *, subjects: tuple[SubjectDescriptor, ...] | None = None,
    aspect: str = ASPECT_CONFIGURATION,
) -> tuple[tuple[str, str], ...]:
    """Subjects whose declared half finds no other half — a registry
    disagreement surfaced as (subject key, explanation) diagnostics.

    Configuration: declared tags select no pack rule. State: a
    declared observation kind that no state rule judges.
    """

    roster = subjects if subjects is not None else SUBJECTS
    rows: list[tuple[str, str]] = []
    if aspect == ASPECT_STATE:
        from .state_rules import rules_for_kind

        for descriptor in roster:
            kind = str(getattr(descriptor, "state_kind", "") or "")
            if kind and not tuple(
                rule for rule in rules_for_kind(kind)
                if rule.subject == descriptor.key
            ):
                rows.append((
                    descriptor.key,
                    f"{descriptor.label} declares the observation kind "
                    f"{kind} but no installed state rule judges it.",
                ))
        return tuple(rows)
    active = _active_pack(pack)
    for descriptor in roster:
        if descriptor.policy_tags and not _selected_rules(descriptor, active):
            rows.append((
                descriptor.key,
                f"{descriptor.label} declares policy tags "
                f"({', '.join(descriptor.policy_tags)}) but the active "
                f"pack {active.pack_id}@{active.version} installs no "
                "rule carrying any of them.",
            ))
    return tuple(rows)


# -- the STATE verdict projection (PR-173) ------------------------------------
#
# Six terms mirroring configuration's six one-for-one, sharing the
# honest tail (Not enough evidence / Not applicable / Unsupported use
# the SAME words on both axes — three phrases, not six). The two
# vocabularies never blend: configuration says Compliant, state says
# Healthy, and no answer may use both words about one aspect.

VERDICT_HEALTHY = "Healthy"
VERDICT_DEGRADED = "Degraded"
VERDICT_FAILED = "Failed"
# RESERVED (PR-173): "Unstable" means state changed repeatedly across
# observations — a determination that requires a state HISTORY Atlas
# does not yet retain. The word is defined here so it cannot be reused
# for something weaker, and it is NEVER emitted; a question asking for
# it is refused honestly.
VERDICT_UNSTABLE = "Unstable"


def state_verdict_for(aggregate, *, scope_count: int = 0) -> dict[str, str]:
    """The state verdict projection for one subject's aggregate.

    Pure, like :func:`verdict_for`. The aggregate's counts are per
    (device, rule) determinations from the CORTEX engine plus the
    freshness gate's exclusions (``stale``): a stale device is
    UNJUDGED — never healthy, never failing.
    """

    counts = aggregate.get("counts") or {}
    passed = int(counts.get("pass") or 0)
    failed = int(counts.get("fail") or 0)
    unknown = int(counts.get("unknown") or 0)
    stale = int(counts.get("stale") or 0)
    not_applicable = int(counts.get("not_applicable") or 0)
    judged = passed + failed
    evaluated_devices = len(aggregate.get("devices_evaluated") or ())
    unevaluated = max(0, scope_count - evaluated_devices)

    if judged == 0:
        if (unknown == 0 and stale == 0 and unevaluated == 0
                and not_applicable):
            return {
                "verdict": VERDICT_NOT_APPLICABLE,
                "tone": _TONE_INFO,
                "cause": "no device in scope runs this subject",
            }
        return {
            "verdict": VERDICT_NO_EVIDENCE,
            "tone": _TONE_UNKNOWN,
            "cause": (
                "the observations are too old to support a verdict"
                if stale and unknown == 0 and unevaluated == 0
                else "no device in scope could be judged"
            ),
        }

    if failed:
        severities = {
            str(row.get("severity") or "")
            for row in aggregate.get("rules") or ()
            if int(row.get("fail") or 0)
        }
        lenient = bool(severities) and severities <= _LENIENT_SEVERITIES
        observations = aggregate.get("observations") or {}
        in_state = int(observations.get("ok") or 0)
        total = int(observations.get("total") or 0)
        # Failed vs Degraded is decided at the OBSERVATION level —
        # "27 of 28 Established" is Degraded even when every judged
        # evaluation failed, because most sessions ARE up. Failed
        # means NOTHING is in its expected state.
        if total and in_state == 0:
            return {
                "verdict": VERDICT_FAILED,
                "tone": _TONE_ATTENTION,
                "cause": "no observation is in its expected state",
            }
        return {
            "verdict": VERDICT_DEGRADED,
            "tone": _TONE_WARNING if lenient else _TONE_ATTENTION,
            "cause": f"{max(0, total - in_state)} of {total} "
                     "observation(s) are outside their expected state",
        }

    return {
        "verdict": VERDICT_HEALTHY,
        "tone": _TONE_OK,
        "cause": "every judged observation set is in its expected state",
    }


# -- the verdict projection (PR-172, review §6) -------------------------------
#
# Six terms, each a PROJECTION of determinations Atlas already makes —
# computed from the aggregate, never stored, and each mapped onto an
# EXISTING Experience-Language chip. No fifth status vocabulary.
#
#   Verdict              Defined by                       Chip
#   Compliant            >=1 judged; no fail/warning      Healthy
#   Non-compliant        >=1 applicable rule failed       Attention required
#                                                         (critical/high) ·
#                                                         Warning (medium/low)
#   Partially verified   some judged, some unjudged       Warning
#   Not enough evidence  nothing judged, evidence absent  Not enough evidence
#   Not applicable       everything evaluated, nothing    Informational
#                        applied
#   Unsupported          no capability — no rules, or no  Informational
#                        collection (cause always named)

VERDICT_COMPLIANT = "Compliant"
VERDICT_NON_COMPLIANT = "Non-compliant"
VERDICT_PARTIAL = "Partially verified"
VERDICT_NO_EVIDENCE = "Not enough evidence"
VERDICT_NOT_APPLICABLE = "Not applicable"
VERDICT_UNSUPPORTED = "Unsupported"

# Experience-Language tone keys (advisor/presentation.py) — reused,
# never extended.
_TONE_OK = "ok"
_TONE_ATTENTION = "attention"
_TONE_WARNING = "warning"
_TONE_UNKNOWN = "unknown"
_TONE_INFO = "info"

_LENIENT_SEVERITIES = frozenset(("medium", "low", "info"))


def verdict_for(aggregate, *, scope_count: int = 0) -> dict[str, str]:
    """The verdict projection for one subject's aggregate.

    Pure: reads the counts the policy engine produced and nothing
    else. ``scope_count`` is how many devices the question's scope
    resolved to — the number that makes "partially verified" honest
    (devices the engine never saw are unjudged, not silently absent).
    ``Unsupported`` is not produced here: with no capability there is
    no aggregate to project, and the refusal paths own that wording.
    """

    counts = aggregate.get("counts") or {}
    passed = int(counts.get("pass") or 0)
    failed = int(counts.get("fail") or 0)
    warned = int(counts.get("warning") or 0)
    unknown = int(counts.get("unknown") or 0)
    not_applicable = int(counts.get("not_applicable") or 0)
    judged = passed + failed + warned
    evaluated_devices = len(aggregate.get("devices_evaluated") or ())
    unevaluated = max(0, scope_count - evaluated_devices)

    if judged == 0:
        if unknown == 0 and unevaluated == 0 and not_applicable:
            return {
                "verdict": VERDICT_NOT_APPLICABLE,
                "tone": _TONE_INFO,
                "cause": "every evaluation was excluded by "
                         "applicability — the subject is not "
                         "configured on any device in scope",
            }
        return {
            "verdict": VERDICT_NO_EVIDENCE,
            "tone": _TONE_UNKNOWN,
            "cause": "no device in scope could be judged",
        }

    if failed or warned:
        severities = {
            str(row.get("severity") or "")
            for row in aggregate.get("policies") or ()
            if int(row.get("fail") or 0) or int(row.get("warning") or 0)
        }
        # Grave unless PROVEN lenient: an unknown or undeclared
        # severity keeps the Attention chip — a verdict is never
        # softened by missing metadata.
        lenient = bool(severities) and severities <= _LENIENT_SEVERITIES
        return {
            "verdict": VERDICT_NON_COMPLIANT,
            "tone": _TONE_WARNING if lenient else _TONE_ATTENTION,
            "cause": f"{failed + warned} applicable evaluation(s) did "
                     "not pass",
        }

    if unknown or unevaluated:
        return {
            "verdict": VERDICT_PARTIAL,
            "tone": _TONE_WARNING,
            "cause": f"{unknown + unevaluated} device(s) or "
                     "evaluation(s) in scope could not be judged",
        }

    return {
        "verdict": VERDICT_COMPLIANT,
        "tone": _TONE_OK,
        "cause": "every applicable evaluation passed",
    }


__all__ = [
    "ASPECTS",
    "ASPECT_CONFIGURATION",
    "ASPECT_STATE",
    "ValidationCapability",
    "VERDICT_COMPLIANT",
    "VERDICT_DEGRADED",
    "VERDICT_FAILED",
    "VERDICT_HEALTHY",
    "VERDICT_NON_COMPLIANT",
    "VERDICT_NOT_APPLICABLE",
    "VERDICT_NO_EVIDENCE",
    "VERDICT_PARTIAL",
    "VERDICT_UNSTABLE",
    "VERDICT_UNSUPPORTED",
    "capabilities",
    "capability",
    "mask_blind_reason",
    "mask_blind_rules",
    "state_verdict_for",
    "unrealised",
    "verdict_for",
]
