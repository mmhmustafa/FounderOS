"""Deterministic intent detection over the catalog (PR-164, INTENT).

Two layers, evaluated in a fixed order, every decision explainable:

1. ENGINE RESOLUTION — :func:`catalog.engine_rule_match`, the proven
   first-match phrase table. It picks the answering engine exactly as
   the Advisor always has.

2. INTENT REFINEMENT — within the matched engine's registered family,
   ``refine_keywords`` (word-start matches for single tokens, substring
   for phrases) and declared entity signals pick the finest intent that
   the operator's own words support. No signal → the family's base
   intent (its first registration). Ties break toward the earlier
   registration. Refinement never changes the engine.

When NO engine rule matches, the ``fallback_keywords`` declared by the
catalog get one deterministic pass — this is how "Why is BGP unstable?"
reaches the BGP intent instead of Unknown — at MEDIUM confidence,
because the operator's phrasing was inferred from keywords rather than
a direct workflow phrase. Nothing matched at all routes to the honest
Unknown intent. No AI, no fuzzy matching, no guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .catalog import DEFAULT_REGISTRY, ENGINE_UNKNOWN, engine_rule_match
from .registry import IntentDefinition, IntentRegistry


ROUTE_CONFIDENCE_HIGH = "High"
ROUTE_CONFIDENCE_MEDIUM = "Medium"
ROUTE_CONFIDENCE_UNKNOWN = "Unknown"


@dataclass(frozen=True)
class IntentRoute:
    """One routing decision: the intent, the engine that answers, the
    routing confidence, and WHY — every matched signal, in order."""

    intent: IntentDefinition
    engine: str
    confidence: str
    why: tuple[str, ...] = ()
    escalated: bool = False  # no engine phrase — inferred from keywords

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
    """Keywords that appear in the question. Single tokens match at a
    WORD START (so "lan" never fires inside "plan" or "Atlanta");
    phrases with spaces or punctuation match as plain substrings, the
    same semantics as the engine table."""

    hits = []
    for keyword in keywords:
        folded_keyword = keyword.casefold()
        if " " in folded_keyword or not folded_keyword.isalnum():
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
    engine phrase matched. Same scoring and tie-break as refinement."""

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
    registry: IntentRegistry = DEFAULT_REGISTRY,
    sites: Iterable[str] = (),
) -> IntentRoute:
    """The operational intent for one question — deterministic, always
    explained, never guessed."""

    folded = " ".join(str(question or "").casefold().split())
    if not folded:
        return _unknown_route(registry, "The question is empty.")

    matched = engine_rule_match(folded)
    if matched is not None:
        engine, phrase = matched
        why = [f"the question contains “{phrase}”"]
        family = registry.family(engine)
        if not family:
            return _unknown_route(
                registry,
                f"No intent is registered for the {engine} engine.",
            )
        refined = _refine(family, folded, sites)
        if refined is not None:
            intent, refine_why = refined
            why.extend(refine_why)
        else:
            intent = family[0]  # the family's base intent
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
