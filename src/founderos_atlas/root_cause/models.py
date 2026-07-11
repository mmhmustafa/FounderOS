"""Root-cause models: evidence, timeline, hypotheses, analyses, report.

Everything serializes to plain JSON so the GUI, incident reports, briefs,
tests — and one day an AI layer — inspect the same structures. Every
conclusion references evidence by id; nothing here ever holds a secret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ROOT_CAUSE_SCHEMA_VERSION = "1.0.0"

# Causal ordering of categories within one discovery interval. Atlas has
# run-level timestamps, not per-event device clocks, so ordering inside a
# run is causal-rank-based — documented honesty, never invented seconds.
CATEGORY_CONFIGURATION = "configuration"
CATEGORY_INTERFACE = "interface"
CATEGORY_PROTOCOL = "protocol"
CATEGORY_TOPOLOGY = "topology"
CATEGORY_DISCOVERY = "discovery"
CATEGORY_INCIDENT = "incident"

CAUSAL_RANK = {
    CATEGORY_CONFIGURATION: 0,
    CATEGORY_INTERFACE: 1,
    CATEGORY_PROTOCOL: 2,
    CATEGORY_TOPOLOGY: 3,
    CATEGORY_DISCOVERY: 3,
    CATEGORY_INCIDENT: 4,
}

QUALITY_DIRECT = "direct"     # observed by Atlas this run
QUALITY_DERIVED = "derived"   # inferred from artifacts/history


@dataclass(frozen=True)
class EvidenceItem:
    """One normalized observation with everything needed to cite it."""

    evidence_id: str
    category: str
    observed_at: str
    description: str
    source: str                     # artifact the observation came from
    quality: str = QUALITY_DIRECT
    devices: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def causal_rank(self) -> int:
        return CAUSAL_RANK.get(self.category, 5)

    def mentions_interface(self, interface: str) -> bool:
        needle = interface.strip().casefold()
        return any(needle == item.strip().casefold() for item in self.interfaces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "category": self.category,
            "observed_at": self.observed_at,
            "description": self.description,
            "source": self.source,
            "quality": self.quality,
            "devices": list(self.devices),
            "interfaces": list(self.interfaces),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class TimelineEvent:
    """One entry of the deterministic event timeline."""

    at: str
    causal_rank: int
    category: str
    description: str
    devices: tuple[str, ...] = ()
    evidence_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "causal_rank": self.causal_rank,
            "category": self.category,
            "description": self.description,
            "devices": list(self.devices),
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class Hypothesis:
    """One possible root cause with its evidence, for and against."""

    hypothesis_id: str
    kind: str                       # e.g. configuration-change, physical-failure
    statement: str
    confidence: float               # 0.05 .. 0.95, never 1.0
    band: str                       # very-high | high | medium | low
    supporting: tuple[str, ...] = ()      # evidence ids
    contradicting: tuple[str, ...] = ()   # evidence ids
    next_step: str = ""

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "kind": self.kind,
            "statement": self.statement,
            "confidence": round(self.confidence, 2),
            "confidence_percent": self.confidence_percent,
            "band": self.band,
            "supporting": list(self.supporting),
            "contradicting": list(self.contradicting),
            "next_step": self.next_step,
        }


@dataclass(frozen=True)
class RootCauseAnalysis:
    """The full analysis of one observed problem."""

    subject: str                    # "R1 Gi0/1", "SW9", "10.0.0.9"
    subject_kind: str               # interface-failure | device-removed | discovery-failure
    problem: str                    # what was observed
    primary: Hypothesis
    alternatives: tuple[Hypothesis, ...] = ()
    reasoning: tuple[str, ...] = () # ordered, human-readable causal chain
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "subject_kind": self.subject_kind,
            "problem": self.problem,
            "primary": self.primary.to_dict(),
            "alternatives": [item.to_dict() for item in self.alternatives],
            "reasoning": list(self.reasoning),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class RootCauseReport:
    """Everything Atlas can explain about one discovery interval."""

    generated_at: str
    evidence: tuple[EvidenceItem, ...]
    timeline: tuple[TimelineEvent, ...]
    analyses: tuple[RootCauseAnalysis, ...]
    ordering_note: str = (
        "Events within one discovery interval are ordered causally "
        "(configuration -> interface -> protocol -> topology -> incident); "
        "Atlas does not invent per-event clock times."
    )

    @property
    def most_important(self) -> RootCauseAnalysis | None:
        if not self.analyses:
            return None
        return max(
            self.analyses,
            key=lambda item: (item.primary.confidence, item.subject),
        )

    def to_dict(self) -> dict[str, Any]:
        most = self.most_important
        return {
            "schema_version": ROOT_CAUSE_SCHEMA_VERSION,
            "generated_by": "founderos atlas discover",
            "generated_at": self.generated_at,
            "ordering_note": self.ordering_note,
            "evidence": [item.to_dict() for item in self.evidence],
            "timeline": [event.to_dict() for event in self.timeline],
            "analyses": [analysis.to_dict() for analysis in self.analyses],
            "most_important": most.to_dict() if most is not None else None,
        }
