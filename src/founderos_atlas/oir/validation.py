"""Startup validation for intent registrations (PR-164.1, Part 5).

Runs once, at freeze. Returns EVERY problem found — a capability
author fixes the whole list in one pass instead of playing
whack-a-mole. The registry refuses to freeze while any problem exists:
fail fast, before a single question is routed.
"""

from __future__ import annotations

from typing import Iterable

from .vocabulary import EVIDENCE_KINDS, KNOWN_WORKFLOW_PATHS, workflow_path

# The six operational objectives (PR-171). A controlled vocabulary,
# validated at freeze like evidence kinds and workflow paths — a typo'd
# objective would otherwise silently dispatch to the engine default and
# the intent's declared shape would never fire.
KNOWN_OBJECTIVES = frozenset((
    "validate", "assess", "locate", "explain", "compare", "forecast",
))


def validate_definitions(definitions: Iterable) -> list[str]:
    """Every validation problem across the whole registration set."""

    problems: list[str] = []
    seen_names: dict[str, str] = {}
    seen_phrases: dict[str, str] = {}
    seen_priorities: dict[int, str] = {}
    defaults_by_engine: dict[str, list[str]] = {}
    engines_seen: set[str] = set()

    for definition in definitions:
        key = definition.key
        # -- required fields ------------------------------------------
        for field in ("name", "key", "description", "engine", "domain",
                      "capability", "confidence_rule"):
            if not str(getattr(definition, field, "") or "").strip():
                problems.append(f"{key!r}: {field} must not be empty")
        engines_seen.add(definition.engine)

        # -- declarations are plain data: tuples of strings -----------
        for field in ("examples", "routing_phrases", "required_evidence",
                      "refine_keywords", "refine_entities",
                      "fallback_keywords", "limitations"):
            values = getattr(definition, field, ())
            if not all(isinstance(item, str) for item in values):
                problems.append(
                    f"{key!r}: every entry in {field} must be a string"
                )

        # -- objective is a controlled vocabulary ----------------------
        if getattr(definition, "objective", "assess") not in KNOWN_OBJECTIVES:
            problems.append(
                f"{key!r}: unknown objective "
                f"{getattr(definition, 'objective', '')!r} — use one of: "
                + ", ".join(sorted(KNOWN_OBJECTIVES))
            )

        # -- the honest fallback contract -----------------------------
        if definition.key == "unknown" and definition.engine != "unknown":
            problems.append(
                f"{key!r}: the intent keyed 'unknown' must declare "
                "engine 'unknown' — it is the router's honest fallback"
            )

        # -- duplicate names ------------------------------------------
        folded_name = definition.name.casefold()
        if folded_name in seen_names:
            problems.append(
                f"{key!r}: duplicate intent name {definition.name!r} "
                f"(also registered by {seen_names[folded_name]!r})"
            )
        else:
            seen_names[folded_name] = key

        # -- routing phrases and priorities ---------------------------
        for phrase in definition.routing_phrases:
            folded = str(phrase).casefold()
            if not folded.strip():
                problems.append(f"{key!r}: empty routing phrase")
                continue
            if len(folded.strip()) < 4:
                # A very short phrase is a collision waiting to happen:
                # even word-anchored, "up" or "ok" would fire inside
                # ordinary prose. Direct phrases are HIGH-confidence
                # routes; anything this short belongs in
                # fallback_keywords, which route at Medium.
                problems.append(
                    f"{key!r}: routing phrase {phrase!r} is shorter than "
                    "4 characters — too collision-prone for a "
                    "High-confidence direct route; use fallback_keywords"
                )
            if str(phrase) != folded:
                # Matching runs over the casefolded question; a
                # mixed-case phrase would pass validation yet never
                # fire — a silent dead route.
                problems.append(
                    f"{key!r}: routing phrase {phrase!r} must be "
                    "lowercase (questions are casefolded before "
                    "matching)"
                )
            if folded in seen_phrases:
                problems.append(
                    f"{key!r}: routing phrase {phrase!r} is already "
                    f"claimed by {seen_phrases[folded]!r} — one phrase, "
                    "one owner"
                )
            else:
                seen_phrases[folded] = key
        if definition.routing_phrases:
            priority = definition.routing_priority
            if priority <= 0:
                problems.append(
                    f"{key!r}: declares routing phrases but no positive "
                    "routing_priority — ordering must be explicit"
                )
            elif priority in seen_priorities:
                problems.append(
                    f"{key!r}: routing_priority {priority} conflicts "
                    f"with {seen_priorities[priority]!r} — priorities "
                    "must be unique so first-match stays deterministic"
                )
            else:
                seen_priorities[priority] = key
        elif definition.routing_priority:
            problems.append(
                f"{key!r}: routing_priority without routing phrases"
            )

        # -- engine defaults ------------------------------------------
        if definition.default_for_engine:
            defaults_by_engine.setdefault(definition.engine, []).append(key)

        # -- workflow references --------------------------------------
        for workflow in definition.workflows + definition.recommendations:
            if not workflow.label.strip() or not workflow.why.strip():
                problems.append(
                    f"{key!r}: workflow {workflow.href!r} needs a label "
                    "and a why — recommendations always explain themselves"
                )
            path = workflow_path(workflow.href)
            if path not in KNOWN_WORKFLOW_PATHS:
                problems.append(
                    f"{key!r}: unknown workflow reference "
                    f"{workflow.href!r} (path {path!r} is not a known "
                    "workflow surface — add it to oir/vocabulary.py if "
                    "it is real)"
                )

        # -- evidence definitions -------------------------------------
        for evidence in definition.required_evidence:
            if evidence not in EVIDENCE_KINDS:
                problems.append(
                    f"{key!r}: unknown evidence kind {evidence!r} — "
                    "use a canonical name from oir/vocabulary.py"
                )

        # -- follow-up seeds ------------------------------------------
        for seed in definition.followups:
            if not seed.label.strip() or not seed.question.strip():
                problems.append(
                    f"{key!r}: follow-up seeds need a label and a "
                    "question"
                )

    # -- exactly one default per engine present ------------------------
    for engine in sorted(engines_seen):
        declared = defaults_by_engine.get(engine, [])
        if len(declared) == 0:
            problems.append(
                f"engine {engine!r}: no intent declares "
                "default_for_engine — a bare engine match would have "
                "nowhere honest to land"
            )
        elif len(declared) > 1:
            problems.append(
                f"engine {engine!r}: {len(declared)} intents declare "
                f"default_for_engine ({', '.join(map(repr, declared))}) "
                "— exactly one is allowed"
            )

    return problems
