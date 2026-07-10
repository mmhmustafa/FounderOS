"""Deterministic DashboardSummary to standalone HTML rendering.

Same pattern as the topology viewer: a plain HTML template with token
substitution. No JavaScript frameworks, no CDN, no backend — the dashboard
is a static, self-contained page.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .summary import DashboardSummary


class DashboardRenderer:
    def __init__(self, summary: DashboardSummary) -> None:
        if not isinstance(summary, DashboardSummary):
            raise TypeError("summary must be a DashboardSummary")
        self._summary = summary

    def render(self) -> str:
        template_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
        template = template_path.read_text(encoding="utf-8")
        summary = self._summary
        return (
            template
            .replace("__LAST_DISCOVERY__", escape(summary.last_discovery))
            .replace("__STATUS_CLASS__", escape(summary.status.casefold()))
            .replace("__STATUS_TEXT__", escape(summary.status))
            .replace("__STATUS_DETAIL__", escape(summary.status_detail))
            .replace("__TILES__", self._tiles())
            .replace("__INTELLIGENCE__", self._intelligence())
            .replace("__CHANGES__", self._changes())
            .replace("__ACTIVITY__", self._activity())
            .replace("__DISCOVERIES__", self._discoveries())
            .replace("__CONFIG_CHANGES__", self._configuration_changes())
            .replace("__OPERATIONAL__", self._operational_changes())
            .replace("__INCIDENT__", self._incident())
            .replace("__ACTIONS__", self._actions())
        )

    def _tiles(self) -> str:
        summary = self._summary
        tiles = []
        if summary.health_score is not None:
            tiles.append(
                (
                    "Enterprise Health",
                    f"{summary.health_score}/100 ({summary.health_trend})",
                )
            )
        tiles.extend(
            (
                ("Devices", _value(summary.device_count)),
                ("Relationships", _value(summary.relationship_count)),
                ("Discovery Success", summary.discovery_success),
                ("Configurations Collected", str(summary.configurations_collected)),
                ("Recent Changes", _value(summary.change_count)),
            )
        )
        return "\n".join(
            f'      <div class="tile"><strong>{escape(label)}</strong>'
            f'<span class="value">{escape(value)}</span></div>'
            for label, value in tiles
        )

    def _intelligence(self) -> str:
        summary = self._summary
        if summary.health_score is None:
            return (
                "          <li>No intelligence report yet. "
                "Run: founderos atlas discover</li>"
            )
        entries = [
            f"Enterprise Health: {summary.health_score}/100",
            f"Trend: {summary.health_trend}",
            f"Confidence: {summary.health_confidence}",
        ]
        entries.extend(f"Priority: {item}" for item in summary.priority_queue[:3])
        entries.extend(
            f"Recommendation: {item}" for item in summary.top_recommendations[:3]
        )
        entries.extend(f"Improvement: {item}" for item in summary.improvements)
        entries.extend(f"Regression: {item}" for item in summary.regressions)
        return "\n".join(f"          <li>{escape(entry)}</li>" for entry in entries)

    def _changes(self) -> str:
        summary = self._summary
        if not summary.recent_changes:
            message = (
                "No recent changes."
                if summary.change_count is not None
                else "No change report yet. Run: founderos atlas compare"
            )
            return f"          <li>{escape(message)}</li>"
        items = []
        for entry in summary.recent_changes:
            severity = entry[1 : entry.index("]")] if entry.startswith("[") else "info"
            items.append(
                f'          <li class="{escape(severity)}">{escape(entry)}</li>'
            )
        return "\n".join(items)

    def _activity(self) -> str:
        return "\n".join(
            f"          <li>{escape(entry)}</li>"
            for entry in self._summary.recent_activity
        )

    def _discoveries(self) -> str:
        entries = self._summary.recent_discoveries
        if not entries:
            return "          <li>No discovery history yet.</li>"
        return "\n".join(f"          <li>{escape(entry)}</li>" for entry in entries)

    def _configuration_changes(self) -> str:
        entries = self._summary.configuration_changes
        if not entries:
            return (
                "          <li>No configuration change report yet. "
                "Run: founderos atlas config-diff</li>"
            )
        return "\n".join(f"          <li>{escape(entry)}</li>" for entry in entries)

    def _operational_changes(self) -> str:
        entries = self._summary.operational_changes
        if not entries:
            return (
                "          <li>No operational change report yet. "
                "Run: founderos atlas state-diff</li>"
            )
        return "\n".join(f"          <li>{escape(entry)}</li>" for entry in entries)

    def _incident(self) -> str:
        entries = self._summary.incident_investigation
        if not entries:
            return "          <li>No incident investigation yet.</li>"
        return "\n".join(f"          <li>{escape(entry)}</li>" for entry in entries)

    def _actions(self) -> str:
        fragments = []
        for action in self._summary.actions:
            if action.href is not None:
                fragments.append(
                    f'        <a class="action" href="{escape(action.href, quote=True)}">'
                    f"{escape(action.label)}</a>"
                )
            else:
                fragments.append(
                    f'        <span class="action disabled">{escape(action.label)}'
                    f" (not yet generated)</span>"
                )
        return "\n".join(fragments)


def _value(value: int | None) -> str:
    return "—" if value is None else str(value)
