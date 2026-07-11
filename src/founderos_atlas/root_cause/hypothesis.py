"""Hypothesis engine: rule-based possible root causes, ranked by evidence.

Every observed problem (a failed interface, a vanished device, a device
that would not answer discovery) gets a set of competing hypotheses. Each
hypothesis lists the evidence supporting it AND the evidence contradicting
it — a configuration change on the failing device *supports* the
configuration hypothesis and *contradicts* the hardware hypothesis, exactly
the way an engineer weighs it.
"""

from __future__ import annotations

from .confidence import band, calculate
from .graph import CausalGraph
from .models import (
    CATEGORY_CONFIGURATION,
    CATEGORY_DISCOVERY,
    CATEGORY_INTERFACE,
    CATEGORY_PROTOCOL,
    CATEGORY_TOPOLOGY,
    EvidenceItem,
    Hypothesis,
)


def problem_subjects(
    evidence: tuple[EvidenceItem, ...],
) -> tuple[tuple[str, str, EvidenceItem], ...]:
    """(subject_kind, subject, anchor evidence) for every observed problem."""

    subjects: list[tuple[str, str, EvidenceItem]] = []
    seen: set[str] = set()
    for item in evidence:
        if item.category in (CATEGORY_INTERFACE, CATEGORY_PROTOCOL):
            if item.attributes.get("event") not in ("failure", "degradation"):
                continue
            subject = f"{item.devices[0]} {item.interfaces[0]}" if item.devices else item.evidence_id
            key = f"interface-failure:{subject.casefold()}"
            if key not in seen:
                seen.add(key)
                subjects.append(("interface-failure", subject, item))
        elif item.category == CATEGORY_TOPOLOGY and item.attributes.get("change") == "removed":
            subject = item.devices[0] if item.devices else item.evidence_id
            key = f"device-removed:{subject.casefold()}"
            if key not in seen:
                seen.add(key)
                subjects.append(("device-removed", subject, item))
        elif item.category == CATEGORY_DISCOVERY:
            subject = item.devices[0] if item.devices else item.evidence_id
            key = f"discovery-failure:{subject.casefold()}"
            if key not in seen:
                seen.add(key)
                subjects.append(("discovery-failure", subject, item))
    subjects.sort(key=lambda entry: (entry[0], entry[1].casefold()))
    return tuple(subjects)


def generate_hypotheses(
    subject_kind: str,
    subject: str,
    anchor: EvidenceItem,
    evidence: tuple[EvidenceItem, ...],
    graph: CausalGraph,
    *,
    recurring: bool = False,
    stale: bool = False,
) -> tuple[Hypothesis, ...]:
    if subject_kind == "interface-failure":
        hypotheses = _interface_hypotheses(subject, anchor, evidence, stale=stale)
    elif subject_kind == "device-removed":
        hypotheses = _removed_hypotheses(subject, anchor, evidence, graph, stale=stale)
    else:
        hypotheses = _discovery_hypotheses(subject, anchor, recurring=recurring, stale=stale)
    return tuple(
        sorted(hypotheses, key=lambda item: (-item.confidence, item.kind))
    )


def _interface_hypotheses(
    subject: str, anchor: EvidenceItem, evidence: tuple[EvidenceItem, ...], *, stale: bool
) -> list[Hypothesis]:
    device = anchor.devices[0] if anchor.devices else "the device"
    interface = anchor.interfaces[0] if anchor.interfaces else "the interface"
    config_items = [
        item
        for item in evidence
        if item.category == CATEGORY_CONFIGURATION
        and device.casefold() in {name.casefold() for name in item.devices}
    ]
    interface_match = any(
        item.mentions_interface(interface) for item in config_items
    )
    related_state = [
        item
        for item in evidence
        if item.category in (CATEGORY_INTERFACE, CATEGORY_PROTOCOL)
        and item.mentions_interface(interface)
        and item.attributes.get("event") in ("failure", "degradation")
    ]
    admin_down = any(
        "administratively" in str(item.attributes.get("current_value"))
        for item in related_state
    )
    hypotheses: list[Hypothesis] = []
    if config_items:
        confidence = calculate(
            0.60,
            supporting=len(config_items) + len(related_state),
            interface_match=interface_match,
            stale=stale,
        )
        hypotheses.append(
            Hypothesis(
                hypothesis_id=f"configuration-change:{subject}",
                kind="configuration-change",
                statement=(
                    f"A recent configuration change on {device} shut or "
                    f"altered {interface}."
                ),
                confidence=confidence,
                band=band(confidence),
                supporting=tuple(
                    item.evidence_id for item in config_items + related_state
                ),
                next_step=(
                    f"Compare {device}'s configuration diff before "
                    "investigating hardware."
                ),
            )
        )
    physical_confidence = calculate(
        0.55 if not config_items else 0.35,
        supporting=len(related_state),
        contradicting=len(config_items) + (1 if admin_down else 0),
        stale=stale,
    )
    hypotheses.append(
        Hypothesis(
            hypothesis_id=f"physical-failure:{subject}",
            kind="physical-failure",
            statement=(
                f"A physical link, optic, or remote-end failure took "
                f"{interface} on {device} down."
            ),
            confidence=physical_confidence,
            band=band(physical_confidence),
            supporting=tuple(item.evidence_id for item in related_state),
            contradicting=tuple(item.evidence_id for item in config_items),
            next_step=(
                "Check the physical link and the device at the far end, then "
                "re-run discovery to confirm recovery."
            ),
        )
    )
    if admin_down and not config_items:
        deliberate = calculate(0.5, supporting=len(related_state), stale=stale)
        hypotheses.append(
            Hypothesis(
                hypothesis_id=f"deliberate-shutdown:{subject}",
                kind="deliberate-shutdown",
                statement=(
                    f"{interface} on {device} was administratively shut — a "
                    "deliberate action or maintenance outside collected "
                    "configuration evidence."
                ),
                confidence=deliberate,
                band=band(deliberate),
                supporting=tuple(item.evidence_id for item in related_state),
                next_step=(
                    "Check change records for planned maintenance; enable "
                    "configuration collection so future runs can confirm the "
                    "change directly."
                ),
            )
        )
    return hypotheses


def _removed_hypotheses(
    subject: str,
    anchor: EvidenceItem,
    evidence: tuple[EvidenceItem, ...],
    graph: CausalGraph,
    *,
    stale: bool,
) -> list[Hypothesis]:
    upstream = [
        item
        for item in evidence
        if item.category in (CATEGORY_INTERFACE, CATEGORY_PROTOCOL)
        and item.attributes.get("event") in ("failure", "degradation")
        and any(
            target == anchor.evidence_id for target, _ in graph.effects_of(item.evidence_id)
        )
    ]
    hypotheses: list[Hypothesis] = []
    if upstream:
        confidence = calculate(0.60, supporting=len(upstream) + 1, stale=stale)
        upstream_device = upstream[0].devices[0] if upstream[0].devices else "an upstream device"
        hypotheses.append(
            Hypothesis(
                hypothesis_id=f"upstream-isolation:{subject}",
                kind="upstream-isolation",
                statement=(
                    f"{subject} disappeared because its upstream neighbor "
                    f"{upstream_device} lost the connecting interface."
                ),
                confidence=confidence,
                band=band(confidence),
                supporting=(anchor.evidence_id,)
                + tuple(item.evidence_id for item in upstream),
                next_step=(
                    f"Restore the failed interface on {upstream_device} first; "
                    f"{subject} should return on the next discovery."
                ),
            )
        )
    down_confidence = calculate(
        0.45, supporting=1, contradicting=len(upstream), stale=stale
    )
    hypotheses.append(
        Hypothesis(
            hypothesis_id=f"device-down:{subject}",
            kind="device-down",
            statement=f"{subject} itself is down or unreachable.",
            confidence=down_confidence,
            band=band(down_confidence),
            supporting=(anchor.evidence_id,),
            contradicting=tuple(item.evidence_id for item in upstream),
            next_step=f"Verify power and the management path to {subject}.",
        )
    )
    maintenance = calculate(0.30, contradicting=len(upstream), stale=stale)
    hypotheses.append(
        Hypothesis(
            hypothesis_id=f"expected-maintenance:{subject}",
            kind="expected-maintenance",
            statement=(
                f"{subject} was decommissioned or taken down for planned "
                "maintenance."
            ),
            confidence=maintenance,
            band=band(maintenance),
            supporting=(anchor.evidence_id,),
            contradicting=tuple(item.evidence_id for item in upstream),
            next_step="Check change records for planned work before treating "
            "this as an outage.",
        )
    )
    return hypotheses


def _discovery_hypotheses(
    subject: str, anchor: EvidenceItem, *, recurring: bool, stale: bool
) -> list[Hypothesis]:
    hypotheses: list[Hypothesis] = []
    if anchor.attributes.get("auth_failure"):
        confidence = calculate(0.80, supporting=1, stale=stale)
        hypotheses.append(
            Hypothesis(
                hypothesis_id=f"authentication-issue:{subject}",
                kind="authentication-issue",
                statement=(
                    f"Atlas could not authenticate to {subject}: a changed "
                    "password or a credential scoped to the wrong devices."
                ),
                confidence=confidence,
                band=band(confidence),
                supporting=(anchor.evidence_id,),
                next_step=(
                    "Update the profile credential or add a credential-set "
                    f"entry whose scope covers {subject}."
                ),
            )
        )
    unreachable = calculate(
        0.50 if not anchor.attributes.get("auth_failure") else 0.20,
        supporting=1,
        recurring=recurring,
        stale=stale,
    )
    hypotheses.append(
        Hypothesis(
            hypothesis_id=f"unreachable:{subject}",
            kind="device-unreachable",
            statement=(
                f"{subject} is down, unreachable, or blocking SSH"
                + (" — and has failed repeatedly in recent runs." if recurring else ".")
            ),
            confidence=unreachable,
            band=band(unreachable),
            supporting=(anchor.evidence_id,),
            next_step=(
                f"Verify power and the management path to {subject}, confirm "
                "SSH is enabled, then run discovery again."
            ),
        )
    )
    return hypotheses
