"""Enterprise configuration change timeline (PR-044, Part 7).

Turns remembered versions into a chronological narrative:

    Yesterday
      Core1    Configuration Changed          09:42
      Edge2    BGP Neighbor Removed           11:03
      Access1  Interface Description Updated  15:28

Each entry is a real version transition (vN-1 → vN) with a semantic
summary derived from the normalized facts of both versions. Version 1 is
the device's first remembered configuration — reported as a baseline, not
a change (Atlas never claims something changed when it has nothing to
compare against).

Mission, Advisor, and Prediction consume this later (Part 10) — this PR
only builds the foundation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .extract import extract_facts
from .models import DeviceConfigHistory, TimelineEvent
from .semantic import highest_severity, semantic_diff, summarize_events


BASELINE_SUMMARY = "First configuration recorded (baseline)"


def device_timeline(
    history: DeviceConfigHistory,
    *,
    config_text,
    include_baseline: bool = True,
) -> tuple[TimelineEvent, ...]:
    """The change timeline for one device, newest first.

    ``config_text`` is a callable ``sha256 -> text | None`` (typically
    ``ConfigMemoryStore.config_text``) so the timeline reads blobs lazily
    and stays testable without a filesystem.
    """

    events: list[TimelineEvent] = []
    versions = history.versions
    for index, version in enumerate(versions):
        if index == 0:
            if include_baseline:
                events.append(
                    TimelineEvent(
                        occurred_at=version.first_seen,
                        device_id=history.device_id,
                        hostname=history.hostname,
                        network=history.network,
                        version=version.version,
                        previous_version=None,
                        summary=BASELINE_SUMMARY,
                        change_count=0,
                        discovery_session=version.snapshot.discovery_session,
                        highest_severity="low",
                    )
                )
            continue
        previous = versions[index - 1]
        before_text = config_text(previous.config_sha256)
        after_text = config_text(version.config_sha256)
        if before_text is None or after_text is None:
            # Honest degradation: the blob is missing, so Atlas reports the
            # transition without claiming to know what changed.
            events.append(
                TimelineEvent(
                    occurred_at=version.first_seen,
                    device_id=history.device_id,
                    hostname=history.hostname,
                    network=history.network,
                    version=version.version,
                    previous_version=previous.version,
                    summary=(
                        "Configuration changed (stored text unavailable — "
                        "semantic detail unknown)"
                    ),
                    change_count=0,
                    discovery_session=version.snapshot.discovery_session,
                    highest_severity="low",
                )
            )
            continue
        semantic = semantic_diff(
            extract_facts(before_text), extract_facts(after_text)
        )
        events.append(
            TimelineEvent(
                occurred_at=version.first_seen,
                device_id=history.device_id,
                hostname=history.hostname,
                network=history.network,
                version=version.version,
                previous_version=previous.version,
                summary=summarize_events(semantic),
                change_count=len(semantic),
                discovery_session=version.snapshot.discovery_session,
                highest_severity=highest_severity(semantic),
            )
        )
    events.sort(key=lambda item: (item.occurred_at, item.hostname), reverse=True)
    return tuple(events)


def enterprise_timeline(
    histories: tuple[DeviceConfigHistory, ...],
    *,
    config_text,
    include_baseline: bool = False,
    limit: int | None = None,
) -> tuple[TimelineEvent, ...]:
    """One chronological timeline across every remembered device.

    Baselines are excluded by default: an enterprise "what changed" view
    should show changes, not first sightings.
    """

    events: list[TimelineEvent] = []
    for history in histories:
        events.extend(
            device_timeline(
                history, config_text=config_text, include_baseline=include_baseline
            )
        )
    events.sort(key=lambda item: (item.occurred_at, item.hostname), reverse=True)
    return tuple(events[:limit] if limit else events)


def group_by_day(
    events: tuple[TimelineEvent, ...],
    *,
    day_of: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Timeline entries grouped by calendar day, newest day first.

    Pure shaping for the UI — no invented ordering.

    Timestamps are stored in UTC, so the default key (the ISO date prefix)
    groups by the *UTC* day. For an operator west or east of UTC that is the
    wrong day: 02:00 on the 15th in UTC+05:30 was recorded as 20:30 on the
    14th in UTC, and would file under the 14th.

    ``day_of`` lets the rendering boundary supply the operator's own day
    boundary (see ``web.timefmt.day_key_for``). The engine stays deterministic
    and timezone-free; the caller owns the presentation zone.
    """

    key = day_of or (lambda value: str(value)[:10])
    grouped: dict[str, list[TimelineEvent]] = {}
    for event in events:
        day = key(str(event.occurred_at)) or "unknown"
        grouped.setdefault(day, []).append(event)
    return [
        {
            "day": day,
            "events": [event.to_dict() for event in grouped[day]],
            "change_count": len(grouped[day]),
        }
        for day in sorted(grouped, reverse=True)
    ]
