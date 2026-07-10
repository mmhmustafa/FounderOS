"""Finding detection: every event becomes a classified finding.

Severity = how bad the condition itself is. Risk = how much damage it can
do from where it sits (blast radius, recurrence). Confidence = how directly
Atlas observed it. Urgency = when a person should act. All rule-based and
deterministic; every finding carries its evidence.
"""

from __future__ import annotations

from .models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    Finding,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    URGENCY_IMMEDIATE,
    URGENCY_SCHEDULED,
    URGENCY_SOON,
)


def detect_findings(evidence) -> tuple[Finding, ...]:
    """Classify everything in the evidence worth a manager's attention."""

    findings: list[Finding] = []

    for issue in evidence.active_interface_issues:
        hostname = str(issue.get("hostname") or "unknown")
        interface = str(issue.get("interface") or "unknown")
        blast = evidence.neighbor_count(hostname)
        findings.append(
            Finding(
                finding_id=f"interface-failure:{hostname}:{interface}",
                category="interface-failure",
                title=f"Interface down: {hostname} {interface}",
                summary=(
                    f"{interface} on {hostname} is "
                    f"{issue.get('current_value', 'down')} "
                    f"(was {issue.get('previous_value', 'up')})."
                ),
                severity=(
                    SEVERITY_HIGH
                    if str(issue.get("severity")) == "high"
                    else SEVERITY_MEDIUM
                ),
                risk=_blast_risk(blast, recurring=False),
                confidence=CONFIDENCE_HIGH,  # directly observed this run
                urgency=URGENCY_IMMEDIATE,
                subject=hostname,
                blast_radius=blast,
                evidence=(
                    f"{interface} {issue.get('field', 'status')}: "
                    f"{issue.get('previous_value')} -> {issue.get('current_value')}",
                ),
            )
        )

    for host in evidence.auth_failed_hosts:
        recurring = host in evidence.recurring_unstable_hosts
        findings.append(
            Finding(
                finding_id=f"authentication-failure:{host}",
                category="authentication-failure",
                title=f"Authentication failed: {host}",
                summary=(
                    f"Atlas could not authenticate to {host}; its state is "
                    "invisible until credentials are fixed."
                ),
                severity=SEVERITY_HIGH,
                risk=RISK_MEDIUM,
                confidence=CONFIDENCE_HIGH,
                urgency=URGENCY_IMMEDIATE,
                subject=host,
                recurring=recurring,
                evidence=(f"authentication rejected during discovery of {host}",),
            )
        )

    for host in evidence.unreachable_hosts:
        recurring = host in evidence.recurring_unstable_hosts
        findings.append(
            Finding(
                finding_id=f"discovery-failure:{host}",
                category="discovery-failure",
                title=f"Device unreachable: {host}",
                summary=(
                    f"{host} did not answer during discovery; it may be down, "
                    "unreachable, or blocking SSH."
                ),
                severity=SEVERITY_HIGH if recurring else SEVERITY_MEDIUM,
                risk=RISK_MEDIUM if recurring else RISK_LOW,
                confidence=CONFIDENCE_HIGH,
                urgency=URGENCY_SOON,
                subject=host,
                recurring=recurring,
                evidence=(f"{host} failed discovery this run",),
            )
        )

    for hostname in evidence.removed_devices:
        blast = evidence.previous_neighbor_count(hostname)
        findings.append(
            Finding(
                finding_id=f"device-removed:{hostname}",
                category="device-removed",
                title=f"Device no longer discovered: {hostname}",
                summary=(
                    f"{hostname} was present in the previous discovery of this "
                    "network and is now gone."
                ),
                severity=SEVERITY_HIGH,
                risk=_blast_risk(blast, recurring=False),
                confidence=CONFIDENCE_HIGH,
                urgency=URGENCY_IMMEDIATE,
                subject=hostname,
                blast_radius=blast,
                evidence=(f"{hostname} missing versus the previous baseline",),
            )
        )

    for hostname in evidence.config_changed_devices:
        high = hostname in evidence.config_high_changed_devices
        findings.append(
            Finding(
                finding_id=f"configuration-change:{hostname}",
                category="configuration-change",
                title=f"Configuration changed: {hostname}",
                summary=(
                    f"The running configuration of {hostname} changed since the "
                    "previous discovery."
                ),
                severity=SEVERITY_MEDIUM if high else SEVERITY_LOW,
                risk=RISK_MEDIUM if high else RISK_LOW,
                confidence=CONFIDENCE_HIGH,
                urgency=URGENCY_SOON if high else URGENCY_SCHEDULED,
                subject=hostname,
                blast_radius=evidence.neighbor_count(hostname),
                evidence=(f"configuration diff recorded for {hostname}",),
            )
        )

    if evidence.is_stale:
        findings.append(
            Finding(
                finding_id="stale-discovery",
                category="stale-discovery",
                title="Discovery evidence is stale",
                summary=(
                    "The latest discovery of this network is more than a day "
                    "old; current state may differ."
                ),
                severity=SEVERITY_LOW,
                risk=RISK_LOW,
                confidence=CONFIDENCE_HIGH,
                urgency=URGENCY_SCHEDULED,
                subject="discovery",
                evidence=(f"last completed: {evidence.last_completed_at}",),
            )
        )

    # Deterministic order before prioritization: category then subject.
    findings.sort(key=lambda item: (item.category, item.subject, item.finding_id))
    return tuple(findings)


def _blast_risk(blast_radius: int, *, recurring: bool) -> str:
    if blast_radius >= 3:
        return RISK_HIGH
    if blast_radius >= 1 or recurring:
        return RISK_MEDIUM
    return RISK_LOW
