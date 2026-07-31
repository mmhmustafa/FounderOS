"""PRISM prompt registry (PR-165, Part 7).

Prompts are managed DATA, not code: name, version, purpose, declared
variables, safety rules, supported models, and a fallback. Updating a
prompt is a registration change, and every AI audit record names the
prompt version that produced the answer — so an answer can always be
traced to the exact instruction that shaped it.

The safety contract is not per-prompt and not optional. Every rendered
prompt carries :data:`SAFETY_PREAMBLE` first, because the one thing AI
must never do in Atlas is invent, override, or quietly launder
uncertainty. A prompt cannot opt out of it — there is no field for
that, deliberately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


PROMPT_SCHEMA_VERSION = "1.0.0"

# Prepended to EVERY system prompt. Wording is deliberately absolute.
SAFETY_PREAMBLE = (
    "You are an optional presentation layer inside Atlas, an "
    "evidence-based network intelligence system. Atlas — not you — "
    "determines every fact.\n"
    "Rules you must follow without exception:\n"
    "1. Use ONLY the Atlas findings provided below. Never add devices, "
    "addresses, counts, causes, or events that are not present in them.\n"
    "2. Never contradict, soften, or override an Atlas conclusion.\n"
    "3. Preserve uncertainty exactly as Atlas states it. If Atlas says "
    "it does not know, say that it does not know. Never fill a gap "
    "with a guess, an assumption, or a typical case.\n"
    "4. Do not recommend or describe configuration changes, and do not "
    "claim any action has been taken.\n"
    "5. If the findings are insufficient to answer, say so plainly "
    "instead of producing a plausible answer.\n"
    "You are rephrasing evidence for a network engineer. Be concise, "
    "concrete, and neutral."
)

_VARIABLE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class PromptError(ValueError):
    """A prompt could not be rendered."""


@dataclass(frozen=True)
class PromptTemplate:
    """One managed prompt.

    ``system`` and ``user`` are format strings using ``{variable}``
    placeholders — plain substitution, never evaluation. ``fallback``
    is the shorter prompt used when a model's context window cannot
    take the full one.
    """

    name: str
    version: str
    purpose: str
    system: str
    user: str
    variables: tuple[str, ...] = ()
    safety_rules: tuple[str, ...] = ()
    supported_models: tuple[str, ...] = ()   # () = any model
    fallback: str = ""
    owner: str = "Atlas Platform"

    @property
    def identifier(self) -> str:
        """Name and version together — what the audit records."""

        return f"{self.name}@{self.version}"

    def declared_variables(self) -> tuple[str, ...]:
        found = set(_VARIABLE.findall(self.system))
        found |= set(_VARIABLE.findall(self.user))
        return tuple(sorted(found))

    def supports(self, model: str) -> bool:
        return not self.supported_models or model in self.supported_models

    def render(
        self, variables: Mapping[str, Any], *, use_fallback: bool = False
    ) -> tuple[str, str]:
        """(system, user) with variables substituted.

        Every declared variable must be supplied: a missing one would
        silently produce a prompt describing nothing, and an empty
        prompt is exactly how a model starts inventing.
        """

        required = set(self.declared_variables())
        missing = sorted(required - set(variables))
        if missing:
            raise PromptError(
                f"prompt {self.identifier} is missing variable(s): "
                + ", ".join(missing)
            )
        safe = {key: str(value) for key, value in variables.items()}
        body = self.fallback if (use_fallback and self.fallback) else self.user
        try:
            system = self.system.format(**safe)
            user = body.format(**safe)
        except (KeyError, IndexError, ValueError) as error:
            raise PromptError(
                f"prompt {self.identifier} could not be rendered: {error}"
            ) from error
        rules = "".join(f"\n- {rule}" for rule in self.safety_rules)
        return (
            SAFETY_PREAMBLE + (f"\nAdditional rules:{rules}" if rules else "")
            + ("\n\n" + system if system.strip() else ""),
            user,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "purpose": self.purpose,
            "variables": list(self.declared_variables()),
            "safety_rules": list(self.safety_rules),
            "supported_models": list(self.supported_models),
            "has_fallback": bool(self.fallback),
            "owner": self.owner,
        }


class PromptRegistry:
    """Registered prompts, addressed by name."""

    def __init__(self) -> None:
        self._by_name: dict[str, PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> PromptTemplate:
        existing = self._by_name.get(template.name)
        if existing is not None and existing.version == template.version:
            raise ValueError(
                f"prompt {template.name!r} version {template.version} is "
                "already registered — bump the version to change a prompt"
            )
        declared = set(template.declared_variables())
        promised = set(template.variables)
        if promised and promised != declared:
            raise ValueError(
                f"prompt {template.name!r} declares variables "
                f"{sorted(promised)} but uses {sorted(declared)}"
            )
        self._by_name[template.name] = template
        return template

    def get(self, name: str) -> PromptTemplate | None:
        return self._by_name.get(name)

    def all(self) -> tuple[PromptTemplate, ...]:
        return tuple(self._by_name.values())


# -- the built-in prompts ---------------------------------------------------

PROMPT_PLAIN_ENGLISH = "plain-english"
PROMPT_EXECUTIVE_SUMMARY = "executive-summary"
PROMPT_INCIDENT_SUMMARY = "incident-summary"
PROMPT_REPORT = "report-narrative"
PROMPT_QUESTION_REWRITE = "question-rewrite"
PROMPT_TRANSLATION = "translation"


def build_default_prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    # 1.1.0 (PR-166): audience-aware. The reader changes; the findings
    # never do. ``limitations`` is passed explicitly so what Atlas could
    # NOT determine travels with the finding instead of being dropped on
    # the way to the model.
    registry.register(PromptTemplate(
        name=PROMPT_PLAIN_ENGLISH, version="1.1.0",
        purpose="Restate an Atlas answer in plain English for a named "
                "audience, changing nothing.",
        system="Rewrite the finding for this reader: {audience}\n"
               "Keep every number, hostname and interface name exactly "
               "as given.",
        user="Atlas finding:\n{finding}\n\n"
             "Confidence stated by Atlas: {confidence}\n"
             "What Atlas could not determine: {limitations}\n\n"
             "Rewrite it in at most 4 short sentences for the reader "
             "described above. If Atlas could not determine something, "
             "say so in your own words — do not omit it.",
        safety_rules=(
            "Do not add causes or consequences Atlas did not state.",
            "Keep the stated confidence visible in your wording.",
            "Never present an unknown as resolved or unimportant.",
        ),
        fallback="Atlas finding:\n{finding}\n\nRewrite in 2 sentences "
                 "for: {audience}. Confidence: {confidence}. "
                 "Unknowns: {limitations}",
    ))
    registry.register(PromptTemplate(
        name=PROMPT_EXECUTIVE_SUMMARY, version="1.1.0",
        purpose="Summarize Atlas findings for a management audience, in "
                "terms of impact and risk rather than protocol detail.",
        system="Summarize for this reader: {audience}\n"
               "Lead with operational impact and risk, not protocol "
               "detail. Use technical terms only where no plain wording "
               "exists.",
        user="Atlas findings:\n{findings}\n\nScope: {scope}\n"
             "Confidence stated by Atlas: {confidence}\n"
             "What Atlas could not determine: {limitations}\n\n"
             "Write at most 5 short bullet points covering: what the "
             "state is, what needs attention, and what it affects. End "
             "with one line naming what Atlas could not determine.",
        safety_rules=(
            "Never present an unknown as a low risk.",
            "Do not rank or prioritise beyond what the findings support.",
            "Do not estimate cost, downtime or customer numbers — Atlas "
            "does not measure them.",
        ),
        fallback="Atlas findings:\n{findings}\n\nScope: {scope}\n\n"
                 "Write 3 bullet points for: {audience}. "
                 "Unknowns: {limitations}",
    ))
    registry.register(PromptTemplate(
        name=PROMPT_INCIDENT_SUMMARY, version="1.0.0",
        purpose="Narrate an incident timeline Atlas has already built.",
        system="Describe the incident in the order the evidence records "
               "it. The timeline is authoritative.",
        user="Incident evidence:\n{evidence}\n\nWrite a short narrative "
             "for the incident record. Do not speculate about root "
             "cause unless Atlas states one.",
        safety_rules=(
            "Do not assign blame or attribute intent.",
            "Do not infer a root cause Atlas has not concluded.",
        ),
    ))
    registry.register(PromptTemplate(
        name=PROMPT_REPORT, version="1.0.0",
        purpose="Turn structured Atlas report data into prose.",
        system="Write the narrative sections of an operational report "
               "from the supplied data.",
        user="Report data:\n{data}\n\nAudience: {audience}\n\nWrite the "
             "narrative. Every figure must come from the data.",
        safety_rules=(
            "Never introduce a figure that is not in the data.",
        ),
    ))
    registry.register(PromptTemplate(
        name=PROMPT_QUESTION_REWRITE, version="1.0.0",
        purpose="Rewrite an operator's question into the vocabulary "
                "Atlas's deterministic router understands.",
        system="Rewrite the question using standard network operations "
               "vocabulary. Output ONLY the rewritten question.",
        user="Operator question: {question}\n\nAtlas understands "
             "questions about: {vocabulary}\n\nRewritten question:",
        safety_rules=(
            "Never answer the question — only rewrite it.",
            "Preserve every named device, site, or interface exactly.",
        ),
    ))
    registry.register(PromptTemplate(
        name=PROMPT_TRANSLATION, version="1.0.0",
        purpose="Translate an Atlas answer into another language.",
        system="Translate faithfully. Technical identifiers, hostnames "
               "and interface names stay untranslated.",
        user="Translate into {language}:\n\n{text}",
        safety_rules=(
            "Do not summarize or improve the text while translating.",
        ),
    ))
    return registry


DEFAULT_PROMPT_REGISTRY = build_default_prompt_registry()
