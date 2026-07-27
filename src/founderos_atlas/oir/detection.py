"""Deterministic intent detection over the frozen registry (PR-164
INTENT, data-driven since PR-164.1 FOUNDATION).

Three steps, evaluated in a fixed order, every decision explainable:

1. DIRECT ROUTING — the registry's derived routing table (each
   intent's declared ``routing_phrases``, ordered by its declared
   ``routing_priority``; first match wins). A phrase owned by an
   engine's default intent resolves the ENGINE and continues to
   refinement; a phrase owned by a non-default intent selects that
   intent directly.

2. REFINEMENT — within the matched engine's registered family,
   ``refine_keywords`` (word-start matches for single tokens,
   substring for phrases) and declared entity signals pick the finest
   intent the operator's own words support. No signal → the engine's
   declared default intent. Ties break toward the earlier
   registration. Refinement never changes the engine.

3. ESCALATION — only when no direct phrase matched: one pass over
   declared ``fallback_keywords`` — how "Why is BGP unstable?" reaches
   the BGP intent instead of Unknown — at MEDIUM confidence, because
   the intent was inferred from keywords rather than a direct phrase.

Nothing matched at all routes to the honest Unknown intent. No AI, no
fuzzy matching, no guessing. Detection requires a FROZEN registry:
resolution only ever runs against a validated, immutable catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .registry import IntentDefinition, IntentRegistry


ROUTE_CONFIDENCE_HIGH = "High"
ROUTE_CONFIDENCE_MEDIUM = "Medium"
ROUTE_CONFIDENCE_UNKNOWN = "Unknown"

ENGINE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentRoute:
    """One RESOLUTION decision: the intent, the execution engine that
    will answer, the routing confidence, and WHY — every matched
    signal, in order. Execution belongs to the engines, never to OIR."""

    intent: IntentDefinition
    engine: str
    confidence: str
    why: tuple[str, ...] = ()
    escalated: bool = False  # no direct phrase — inferred from keywords

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.name,
            "key": self.intent.key,
            "engine": self.engine,
            "domain": self.intent.domain,
            "confidence": self.confidence,
            "why": list(self.why),
            "escalated": self.escalated,
        }


def _keyword_hits(folded: str, keywords: Iterable[str]) -> list[str]:
    """Keywords that appear in the question. Single tokens — including
    decorated ones like "route ", "port " or "ge-" — match at a WORD
    START, so "lan" never fires inside "plan", "port " never inside
    "report ", and "ge-" never inside "edge-". Only true multi-word
    phrases ("history of", "can i reboot") match as substrings, the
    same semantics as the direct routing phrases."""

    hits = []
    for keyword in keywords:
        folded_keyword = keyword.casefold()
        if " " in folded_keyword.strip():
            if folded_keyword in folded:
                hits.append(keyword)
        elif re.search(rf"\b{re.escape(folded_keyword)}", folded):
            hits.append(keyword)
    return hits


def _named_sites(folded: str, sites: Iterable[str]) -> list[str]:
    named = []
    for site in sites:
        text = str(site or "").casefold().strip()
        if text and re.search(rf"\b{re.escape(text)}\b", folded):
            named.append(str(site))
    return named


def _direct_match(
    registry: IntentRegistry, folded: str
) -> tuple[IntentDefinition, str] | None:
    """(definition, phrase) for the first direct-phrase hit across the
    registry's priority-ordered routing table, else None."""

    for definition, phrases in registry.routing_table():
        for phrase in phrases:
            if phrase in folded:
                return definition, phrase
    return None


def _refine(
    family: tuple[IntentDefinition, ...],
    folded: str,
    sites: Iterable[str],
) -> tuple[IntentDefinition, list[str]] | None:
    """The best-scoring refinement within one engine family, or None
    when no definition earns a signal. Deterministic: scores sum matched
    signals; ties break toward the earlier registration."""

    best: tuple[int, int, IntentDefinition, list[str]] | None = None
    for order, definition in enumerate(family):
        score = 0
        why: list[str] = []
        for hit in _keyword_hits(folded, definition.refine_keywords):
            score += 2
            why.append(f"the question mentions “{hit}”")
        if "site" in definition.refine_entities:
            for site in _named_sites(folded, sites):
                score += 2
                why.append(
                    f"the question names the known site “{site}”"
                )
        if score > 0 and (best is None or score > best[0]):
            best = (score, order, definition, why)
    if best is None:
        return None
    return best[2], best[3]


def _fallback(
    registry: IntentRegistry, folded: str
) -> tuple[IntentDefinition, list[str]] | None:
    """One pass over every definition's ``fallback_keywords`` when no
    direct phrase matched. Same scoring and tie-break as refinement."""

    best: tuple[int, int, IntentDefinition, list[str]] | None = None
    for order, definition in enumerate(registry.definitions()):
        hits = _keyword_hits(folded, definition.fallback_keywords)
        if not hits:
            continue
        score = 2 * len(hits)
        why = [f"the question mentions “{hit}”" for hit in hits]
        if best is None or score > best[0]:
            best = (score, order, definition, why)
    if best is None:
        return None
    return best[2], best[3]


def _unknown_route(registry: IntentRegistry, why: str) -> IntentRoute:
    unknown = registry.get("unknown")
    if unknown is None:  # a custom registry without the fallback intent
        unknown = IntentDefinition(
            name="Unknown", key="unknown",
            description="No operational pattern matched.",
            engine=ENGINE_UNKNOWN, domain="unknown",
        )
    return IntentRoute(
        intent=unknown, engine=ENGINE_UNKNOWN,
        confidence=ROUTE_CONFIDENCE_UNKNOWN, why=(why,), escalated=False,
    )


def detect(
    question: str,
    *,
    registry: IntentRegistry | None = None,
    sites: Iterable[str] = (),
) -> IntentRoute:
    """The operational intent for one question — deterministic, always
    explained, never guessed. With no ``registry``, resolves against
    the default (frozen) capability catalog."""

    if registry is None:
        from .service import default_router

        registry = default_router().registry
    # routing_table() enforces the lifecycle: registries route only
    # after validation + freeze.
    registry.routing_table()

    folded = " ".join(str(question or "").casefold().split())
    if not folded:
        return _unknown_route(registry, "The question is empty.")

    matched = _direct_match(registry, folded)
    if matched is not None:
        definition, phrase = matched
        engine = definition.engine
        why = [f"the question contains “{phrase}”"]
        if not definition.default_for_engine:
            # A direct phrase owned by a specific intent selects it
            # outright — no refinement needed or wanted.
            why.append(
                f"“{phrase}” is a direct phrase of {definition.name}"
            )
            return IntentRoute(
                intent=definition, engine=engine,
                confidence=ROUTE_CONFIDENCE_HIGH, why=tuple(why),
                escalated=False,
            )
        refined = _refine(registry.family(engine), folded, sites)
        if refined is not None:
            intent, refine_why = refined
            why.extend(refine_why)
        else:
            intent = definition  # the engine's declared default
        return IntentRoute(
            intent=intent, engine=engine,
            confidence=ROUTE_CONFIDENCE_HIGH, why=tuple(why),
            escalated=False,
        )

    inferred = _fallback(registry, folded)
    if inferred is not None:
        intent, why = inferred
        why.append(
            "no direct workflow phrase matched, so the intent was "
            "inferred from these keywords"
        )
        return IntentRoute(
            intent=intent, engine=intent.engine,
            confidence=ROUTE_CONFIDENCE_MEDIUM, why=tuple(why),
            escalated=True,
        )

    return _unknown_route(
        registry,
        "No deterministic rule matched — Atlas routes to Unknown rather "
        "than guess.",
    )
