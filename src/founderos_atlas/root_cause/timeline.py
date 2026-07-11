"""Deterministic event timeline.

Ordered by observed timestamp first, then causal rank (configuration
before interface before protocol before topology before incident), then
description — so two runs over identical evidence produce identical
timelines, and ordering inside one discovery interval reflects causality
rather than invented clock precision.
"""

from __future__ import annotations

from .models import EvidenceItem, TimelineEvent


def build_timeline(evidence: tuple[EvidenceItem, ...]) -> tuple[TimelineEvent, ...]:
    ordered = sorted(
        evidence,
        key=lambda item: (
            item.observed_at,
            item.causal_rank,
            item.category,
            item.description,
        ),
    )
    return tuple(
        TimelineEvent(
            at=item.observed_at,
            causal_rank=item.causal_rank,
            category=item.category,
            description=item.description,
            devices=item.devices,
            evidence_id=item.evidence_id,
        )
        for item in ordered
    )
