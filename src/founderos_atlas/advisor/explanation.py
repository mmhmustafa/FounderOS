"""Advisor's optional AI explanation layer (PR-166, INSIGHT).

The first production consumer of PRISM. It does exactly one thing:
take an answer Atlas has ALREADY produced and ask a model to say it
differently — for a different reader, or in a different language.

What this module may not do, and structurally cannot:

* re-run an engine, re-read evidence, or change a stored answer — it
  reads the stored response dict and nothing else;
* decide anything. The verdict, confidence, evidence and limitations
  on the page come from Atlas and are rendered before this layer is
  ever called;
* fail loudly. Every failure path returns an :class:`Explanation` with
  ``ok=False``; the page then shows Atlas's own output, which is
  complete on its own.

Audiences change the READER, never the findings. The same stored
answer explained for an executive and for a network engineer must
contain the same facts, the same confidence, and the same unknowns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from founderos_atlas.prism import (
    CAPABILITY_EXECUTIVE_SUMMARY,
    CAPABILITY_PLAIN_ENGLISH,
    CAPABILITY_TRANSLATION,
)
from founderos_atlas.prism import presentation, semantic


# -- audiences (Part 3) -----------------------------------------------------
#
# The label is what the operator picks; the descriptor is what the
# prompt receives. Descriptors say who the reader is and what they care
# about — never what to conclude.

@dataclass(frozen=True)
class Audience:
    key: str
    label: str
    descriptor: str
    capability: str = CAPABILITY_PLAIN_ENGLISH

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label,
                "capability": self.capability}


AUDIENCES: tuple[Audience, ...] = (
    Audience(
        key="engineer", label="Network engineer",
        descriptor="a network engineer who knows routing protocols and "
                   "device configuration, and wants the operational "
                   "detail stated precisely",
    ),
    Audience(
        key="junior", label="Junior engineer",
        descriptor="a junior network engineer who knows the basics but "
                   "not this estate: name the concepts involved and say "
                   "why each finding matters, without talking down",
    ),
    Audience(
        key="soc", label="SOC analyst",
        descriptor="a security operations analyst who cares about "
                   "exposure, unexpected change and what to verify "
                   "next, and who does not administer these devices",
    ),
    Audience(
        key="operations", label="Operations",
        descriptor="an operations engineer on shift who needs to know "
                   "what is affected, whether it is stable, and what to "
                   "escalate",
    ),
    Audience(
        key="manager", label="Manager",
        descriptor="a delivery manager who is not a network specialist "
                   "and needs impact, risk and whether action is "
                   "required",
        capability=CAPABILITY_EXECUTIVE_SUMMARY,
    ),
    Audience(
        key="executive", label="Executive",
        descriptor="a senior executive who needs the operational "
                   "situation, its business impact and its risk in a "
                   "few plain sentences, with no protocol detail",
        capability=CAPABILITY_EXECUTIVE_SUMMARY,
    ),
)

AUDIENCE_BY_KEY = {audience.key: audience for audience in AUDIENCES}
DEFAULT_AUDIENCE = AUDIENCES[0]


# -- languages (Part 4) -----------------------------------------------------
#
# Translation is a SECOND PRISM call over the generated explanation:
# Atlas's evidence is never translated, only the prose about it.

LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("hi", "Hindi"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("pt", "Portuguese"),
    ("ja", "Japanese"),
    ("ar", "Arabic"),
)
LANGUAGE_BY_CODE = dict(LANGUAGES)
DEFAULT_LANGUAGE = "en"

_MAX_EVIDENCE_LINES = 8
_MAX_FINDING_CHARS = 4000


@dataclass(frozen=True)
class Explanation:
    """One AI explanation, or an honest refusal.

    ``ok=False`` is normal and carries no error for the operator to
    read: the page simply shows Atlas's own answer.
    """

    ok: bool
    text: str = ""
    audience: str = ""
    audience_label: str = ""
    language: str = DEFAULT_LANGUAGE
    language_label: str = "English"
    capability: str = ""
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    generated_at: str = ""
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    redaction_summary: str = ""
    translated: bool = False
    reason: str = ""
    # -- semantic redaction (PR-166.2) ------------------------------
    # ``segments`` is the OPERATOR's view of ``text``: the same words,
    # with each alias annotated and linked back to the Atlas object it
    # stands for, subject to the reader's permissions. ``text`` is what
    # the provider produced; these two are deliberately not identical.
    segments: tuple = ()
    privacy_profile: str = ""
    privacy_profile_label: str = ""
    privacy_note: str = ""
    alias_legend: tuple = ()
    semantic_alias_count: int = 0
    masked_field_count: int = 0
    removed_field_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "audience": self.audience,
            "audience_label": self.audience_label,
            "language": self.language,
            "language_label": self.language_label,
            "capability": self.capability,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "redaction_summary": self.redaction_summary,
            "translated": self.translated,
            "reason": self.reason,
            "segments": [segment.to_dict() for segment in self.segments],
            "privacy_profile": self.privacy_profile,
            "privacy_profile_label": self.privacy_profile_label,
            "privacy_note": self.privacy_note,
            "alias_legend": list(self.alias_legend),
            "semantic_alias_count": self.semantic_alias_count,
            "masked_field_count": self.masked_field_count,
            "removed_field_count": self.removed_field_count,
        }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def finding_text(response: Mapping[str, Any]) -> str:
    """The deterministic answer, flattened for a prompt.

    Only what Atlas already concluded: its summary and the LABELS of
    the evidence it cited. Evidence bodies are deliberately excluded —
    the model is being asked to rephrase a conclusion, not to read raw
    device output.
    """

    parts = [_clean(response.get("summary"))]
    evidence = [
        f"- {_clean(item.get('label'))}: {_clean(item.get('detail'))}"
        for item in (response.get("evidence") or ())
        if isinstance(item, Mapping) and _clean(item.get("label"))
    ][:_MAX_EVIDENCE_LINES]
    if evidence:
        parts.append("Evidence Atlas cited:\n" + "\n".join(evidence))
    steps = [_clean(step) for step in (response.get("steps") or ()) if step]
    if steps:
        parts.append("Checks Atlas performed: " + "; ".join(steps[:6]))
    return "\n\n".join(part for part in parts if part)[:_MAX_FINDING_CHARS]


def limitations_text(response: Mapping[str, Any]) -> str:
    """What Atlas could NOT determine — passed explicitly so the model
    cannot quietly drop it."""

    unknowns = [
        _clean(item) for item in (response.get("unknowns") or ()) if item
    ]
    if not unknowns:
        return "Atlas stated no limitations for this answer."
    return " ".join(unknowns)


def explain(
    response: Mapping[str, Any] | None,
    *,
    service,
    audience_key: str = "",
    language: str = DEFAULT_LANGUAGE,
    scope_label: str = "",
    known_names: Iterable[str] = (),
    now: str = "",
    aliases=None,
    can_view: bool = False,
    can_reveal: bool = False,
) -> Explanation:
    """Explain one STORED Atlas answer for one audience and language.

    Never raises: an unusable request, a disabled platform, a refused
    policy or a dead provider all return ``ok=False``.

    ``aliases`` enables semantic redaction (PR-166.2). ``can_view`` and
    ``can_reveal`` are the CALLER's determination, from the
    authenticated user's existing permissions, of whether this reader
    may follow a link to an Atlas object and whether they may see the
    original name behind an alias. This function only honours them; it
    never decides them, and never widens them.
    """

    audience = AUDIENCE_BY_KEY.get(audience_key or "", DEFAULT_AUDIENCE)
    language = language if language in LANGUAGE_BY_CODE else DEFAULT_LANGUAGE
    language_label = LANGUAGE_BY_CODE[language]
    base = Explanation(
        ok=False, audience=audience.key, audience_label=audience.label,
        language=language, language_label=language_label,
        capability=audience.capability,
    )
    if not response:
        return _refused(base, "There is no stored answer to explain.")

    confidence = _clean(response.get("confidence")) or "Unknown"
    finding = finding_text(response)
    if not finding:
        return _refused(base, "The stored answer has no summary to "
                              "explain.")
    limitations = limitations_text(response)

    if audience.capability == CAPABILITY_EXECUTIVE_SUMMARY:
        variables = {
            "findings": finding,
            "scope": scope_label or "this enterprise",
            "confidence": confidence,
            "limitations": limitations,
            "audience": audience.descriptor,
        }
    else:
        variables = {
            "finding": finding,
            "confidence": confidence,
            "limitations": limitations,
            "audience": audience.descriptor,
        }

    result = service.enhance(
        audience.capability, variables,
        known_names=known_names, aliases=aliases,
        evidence_version=_clean(response.get("generated_at")),
    )
    if not result.ok:
        return _refused(base, result.reason)

    text = result.text
    translated = False
    if language != DEFAULT_LANGUAGE:
        # Part 4: translation is its own PRISM capability, audited and
        # costed separately. A failure here keeps the untranslated
        # explanation rather than losing the whole thing.
        # The alias book MUST come along. Without it this second pass
        # runs with an unreconciled name list and no profile, and the
        # generic hostname rule rewrites the aliases the first pass
        # inserted: "the Mumbai Core Router at site Mumbai" came back as
        # "the [redacted:hostname-1] Core Router at site
        # [redacted:hostname-1]" — the alias mangled, the site the Cloud
        # profile promised to preserve masked, and two distinct objects
        # collapsed onto one placeholder.
        translation = service.enhance(
            CAPABILITY_TRANSLATION,
            {"language": language_label, "text": text},
            known_names=known_names, aliases=aliases,
            evidence_version=_clean(response.get("generated_at")),
        )
        if translation.ok and translation.text.strip():
            text = translation.text
            translated = True

    # The operator's view of the same answer. Translation is applied
    # BEFORE this, and a translated alias no longer matches the book —
    # so a translated explanation simply carries no links rather than
    # linking the wrong device.
    active = _active_profile(service)
    segments = presentation.present(
        text, aliases=aliases, active_profile=active,
        can_view=can_view, can_reveal=can_reveal,
        provider=result.provider, model=result.model,
    )
    return Explanation(
        ok=True, text=text,
        audience=audience.key, audience_label=audience.label,
        language=language, language_label=language_label,
        capability=audience.capability,
        provider=result.provider, model=result.model,
        prompt_version=result.prompt_version,
        generated_at=now,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost=result.estimated_cost,
        redaction_summary=result.redaction_summary,
        translated=translated,
        segments=tuple(segments),
        privacy_profile=result.privacy_profile,
        privacy_profile_label=result.privacy_profile_label,
        privacy_note=presentation.describe_disclosure(active, {
            semantic.ALIAS: result.semantic_alias_count,
            semantic.MASK: result.masked_field_count,
            semantic.REMOVE: result.removed_field_count,
        }),
        alias_legend=tuple(presentation.alias_legend(
            result.aliases, can_reveal=can_reveal,
        )),
        semantic_alias_count=result.semantic_alias_count,
        masked_field_count=result.masked_field_count,
        removed_field_count=result.removed_field_count,
    )


def _active_profile(service):
    """The privacy profile in force, tolerant of a stub service in
    tests that has no configuration at all."""

    try:
        return service.config.active_profile()
    except Exception:
        return semantic.profile(semantic.DEFAULT_PROFILE)


def _refused(base: Explanation, reason: str) -> Explanation:
    from dataclasses import replace

    return replace(base, ok=False, reason=reason)


def panel_context(service) -> dict[str, Any]:
    """What the Advisor page needs to render (or hide) the AI panel.

    ``available`` drives the whole panel: with AI disabled the page
    renders exactly as it did before PR-166.
    """

    plain = service.capability_available(CAPABILITY_PLAIN_ENGLISH)
    executive = service.capability_available(CAPABILITY_EXECUTIVE_SUMMARY)
    return {
        "available": bool(plain or executive),
        "plain_english": plain,
        "executive_summary": executive,
        "translation": service.capability_available(CAPABILITY_TRANSLATION),
        "audiences": [
            audience.to_dict() for audience in AUDIENCES
            if (audience.capability == CAPABILITY_PLAIN_ENGLISH and plain)
            or (audience.capability == CAPABILITY_EXECUTIVE_SUMMARY
                and executive)
        ],
        "languages": [
            {"code": code, "label": label} for code, label in LANGUAGES
        ],
        "default_audience": DEFAULT_AUDIENCE.key,
        # Part 5: the operator can see which privacy profile is active
        # BEFORE asking for an explanation, not only afterwards.
        "privacy_profile": _active_profile(service).to_dict(),
        "field_labels": dict(semantic.FIELD_LABELS),
        "action_labels": dict(semantic.ACTION_LABELS),
    }
