"""Trend detection across discoveries. Deterministic, evidence-dated.

The primary trajectory compares this run's health score against the
previous run's archived intelligence report (score delta >= +3 improving,
<= -3 declining, else stable; no previous report = baseline). Secondary
signals read the recent history series: configuration churn, discovery
failure recurrence, topology stability, and device-count movement.
"""

from __future__ import annotations

from .models import (
    TREND_BASELINE,
    TREND_DECLINING,
    TREND_IMPROVING,
    TREND_STABLE,
    TrendSignal,
)


TREND_THRESHOLD = 3


def health_trend(current_score: int, previous_score: int | None) -> tuple[str, str]:
    if previous_score is None:
        return TREND_BASELINE, "first scored discovery — baseline established"
    delta = current_score - previous_score
    if delta >= TREND_THRESHOLD:
        return TREND_IMPROVING, f"health rose from {previous_score} to {current_score}"
    if delta <= -TREND_THRESHOLD:
        return TREND_DECLINING, f"health fell from {previous_score} to {current_score}"
    return TREND_STABLE, f"health steady at {current_score} (was {previous_score})"


def detect_trends(evidence, current_score: int) -> tuple[TrendSignal, ...]:
    signals: list[TrendSignal] = []
    direction, detail = health_trend(current_score, evidence.previous_score)
    signals.append(TrendSignal(name="health", direction=direction, detail=detail))

    # Configuration churn: this run's change count vs the previous run's.
    current_churn = evidence.config_change_count
    previous_churn = evidence.previous_config_change_count
    if previous_churn is not None:
        if current_churn > previous_churn:
            signals.append(
                TrendSignal(
                    name="configuration-churn",
                    direction=TREND_DECLINING,
                    detail=(
                        f"configuration changes rose from {previous_churn} "
                        f"to {current_churn}"
                    ),
                )
            )
        elif current_churn < previous_churn:
            signals.append(
                TrendSignal(
                    name="configuration-churn",
                    direction=TREND_IMPROVING,
                    detail=(
                        f"configuration changes fell from {previous_churn} "
                        f"to {current_churn}"
                    ),
                )
            )
        else:
            signals.append(
                TrendSignal(
                    name="configuration-churn",
                    direction=TREND_STABLE,
                    detail=f"configuration changes steady at {current_churn}",
                )
            )

    # Discovery failure recurrence across the recent history window.
    failure_counts = [len(record.failures) for record in evidence.recent_records]
    if len(failure_counts) >= 2:
        if failure_counts[0] > failure_counts[-1]:
            signals.append(
                TrendSignal(
                    name="discovery-failures",
                    direction=TREND_DECLINING,
                    detail=(
                        f"failed devices per run rose to {failure_counts[0]} "
                        f"over the last {len(failure_counts)} discoveries"
                    ),
                )
            )
        elif failure_counts[0] < failure_counts[-1]:
            signals.append(
                TrendSignal(
                    name="discovery-failures",
                    direction=TREND_IMPROVING,
                    detail=(
                        f"failed devices per run fell to {failure_counts[0]} "
                        f"over the last {len(failure_counts)} discoveries"
                    ),
                )
            )
    if evidence.recurring_unstable_hosts:
        signals.append(
            TrendSignal(
                name="link-instability",
                direction=TREND_DECLINING,
                detail=(
                    "recurring instability: "
                    + ", ".join(evidence.recurring_unstable_hosts[:3])
                ),
            )
        )

    # Topology stability across the recent history window.
    device_counts = [record.device_count for record in evidence.recent_records]
    if len(device_counts) >= 2:
        if len(set(device_counts)) == 1 and evidence.topology_change_count == 0:
            signals.append(
                TrendSignal(
                    name="topology",
                    direction=TREND_STABLE,
                    detail=(
                        f"device count steady at {device_counts[0]} across the "
                        f"last {len(device_counts)} discoveries"
                    ),
                )
            )
        elif device_counts[0] < device_counts[-1]:
            signals.append(
                TrendSignal(
                    name="topology",
                    direction=TREND_DECLINING,
                    detail=(
                        f"device count fell from {device_counts[-1]} to "
                        f"{device_counts[0]}"
                    ),
                )
            )
    return tuple(signals)
