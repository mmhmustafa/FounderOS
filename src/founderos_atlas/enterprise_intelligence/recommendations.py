"""Recommendation engine: likely cause first, then a concrete next step.

Templates are cross-signal: an interface failure on a device whose
configuration also changed this run points at the change, not the
hardware — the way a senior engineer would reason. Deterministic;
recommendations are generated for the prioritized findings in rank order.
"""

from __future__ import annotations

from .models import Finding, Recommendation


def recommend(priorities: tuple[Finding, ...], evidence) -> tuple[Recommendation, ...]:
    return tuple(
        _recommend_one(finding, evidence) for finding in priorities
    )


def _recommend_one(finding: Finding, evidence) -> Recommendation:
    if finding.category == "interface-failure":
        return _interface_failure(finding, evidence)
    if finding.category == "authentication-failure":
        return Recommendation(
            finding_id=finding.finding_id,
            title=f"Fix credentials for {finding.subject}",
            impact=(
                f"{finding.subject} is invisible to Atlas until it can "
                "authenticate; faults there would go unnoticed."
            ),
            likely_cause="A changed password or a credential scoped to the wrong devices.",
            next_step=(
                "Update the profile credential or add a credential-set entry "
                f"whose scope covers {finding.subject}, then run discovery again."
            ),
        )
    if finding.category == "discovery-failure":
        cause = (
            "Repeated failures suggest the device is down or its management "
            "path is broken."
            if finding.recurring
            else "The device may be down, unreachable, or blocking SSH."
        )
        return Recommendation(
            finding_id=finding.finding_id,
            title=f"Investigate reachability of {finding.subject}",
            impact=f"{finding.subject} is missing from topology and health evidence.",
            likely_cause=cause,
            next_step=(
                f"Verify power and the management path to {finding.subject}, "
                "confirm SSH is enabled, then run discovery again."
            ),
        )
    if finding.category == "device-removed":
        impact = (
            f"{finding.subject} connected {finding.blast_radius} neighbor "
            "device(s); its loss can isolate parts of the network."
            if finding.blast_radius
            else f"{finding.subject} disappeared from this network's topology."
        )
        return Recommendation(
            finding_id=finding.finding_id,
            title=f"Confirm whether {finding.subject} was decommissioned",
            impact=impact,
            likely_cause=(
                "Planned decommissioning, a power/link failure, or a "
                "management-path change."
            ),
            next_step=(
                "Check change records for planned work first; if none exists, "
                f"treat {finding.subject} as an outage and verify power and links."
            ),
        )
    if finding.category == "configuration-change":
        return Recommendation(
            finding_id=finding.finding_id,
            title=f"Review the configuration change on {finding.subject}",
            impact=(
                f"{finding.subject} connects {finding.blast_radius} neighbor "
                "device(s); unreviewed changes there carry outage risk."
                if finding.blast_radius
                else "Unreviewed configuration drift accumulates outage risk."
            ),
            likely_cause="A manual or automated change since the previous discovery.",
            next_step=(
                f"Open the configuration diff for {finding.subject} and confirm "
                "the change was intended and change-controlled."
            ),
        )
    if finding.category == "stale-discovery":
        return Recommendation(
            finding_id=finding.finding_id,
            title="Run a fresh discovery",
            impact="Every conclusion ages with its evidence.",
            likely_cause="No discovery has run recently for this network.",
            next_step="Run discovery for this network to refresh the evidence.",
        )
    return Recommendation(
        finding_id=finding.finding_id,
        title=f"Investigate {finding.subject}",
        impact=finding.summary,
        likely_cause="Not enough evidence to name a likely cause.",
        next_step=f"Review the underlying reports for {finding.subject}.",
    )


def _interface_failure(finding: Finding, evidence) -> Recommendation:
    config_changed = finding.subject in evidence.config_changed_devices
    impact = (
        f"{finding.subject} connects {finding.blast_radius} neighbor "
        "device(s); this failure can affect everything behind it."
        if finding.blast_radius
        else f"Connectivity through {finding.subject} is degraded."
    )
    if config_changed:
        # Cross-signal reasoning: change first, hardware second.
        return Recommendation(
            finding_id=finding.finding_id,
            title=f"Investigate {finding.title.replace('Interface down: ', '')}",
            impact=impact,
            likely_cause=(
                f"A configuration change was recorded on {finding.subject} "
                "this run — a shutdown or interface change is the most likely "
                "explanation."
            ),
            next_step=(
                f"Compare {finding.subject}'s configuration diff before "
                "investigating hardware."
            ),
        )
    return Recommendation(
        finding_id=finding.finding_id,
        title=f"Investigate {finding.title.replace('Interface down: ', '')}",
        impact=impact,
        likely_cause=(
            "No configuration change was recorded, so a cable, optic, or "
            "remote-end failure is the most likely explanation."
        ),
        next_step=(
            "Check the physical link and the device at the far end, then "
            "re-run discovery to confirm recovery."
        ),
    )
