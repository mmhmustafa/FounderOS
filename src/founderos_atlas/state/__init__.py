"""Operational state intelligence: interface state change detection."""

from .detector import OperationalStateDetector
from .models import (
    EVENT_DEGRADATION,
    EVENT_FAILURE,
    EVENT_INFORMATIONAL,
    EVENT_RECOVERY,
    EVENT_TYPES,
    SEVERITY_ORDER,
    StateChange,
    StateChangeReport,
)
from .report import render_state_report_json, render_state_report_markdown

__all__ = [
    "EVENT_DEGRADATION",
    "EVENT_FAILURE",
    "EVENT_INFORMATIONAL",
    "EVENT_RECOVERY",
    "EVENT_TYPES",
    "OperationalStateDetector",
    "SEVERITY_ORDER",
    "StateChange",
    "StateChangeReport",
    "render_state_report_json",
    "render_state_report_markdown",
]
