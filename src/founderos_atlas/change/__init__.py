"""Change intelligence: deterministic comparison of Atlas topology snapshots."""

from .detector import ChangeDetector
from .models import (
    CATEGORY_DEVICE,
    CATEGORY_DISCOVERY,
    CATEGORY_HOSTNAME,
    CATEGORY_INTERFACE,
    CATEGORY_MANAGEMENT_IP,
    CATEGORY_NEIGHBOR,
    CATEGORY_OS_VERSION,
    CATEGORY_PLATFORM,
    SEVERITY_ORDER,
    Change,
    ChangeReport,
)
from .report import render_change_report_json, render_change_report_markdown

__all__ = [
    "CATEGORY_DEVICE",
    "CATEGORY_DISCOVERY",
    "CATEGORY_HOSTNAME",
    "CATEGORY_INTERFACE",
    "CATEGORY_MANAGEMENT_IP",
    "CATEGORY_NEIGHBOR",
    "CATEGORY_OS_VERSION",
    "CATEGORY_PLATFORM",
    "Change",
    "ChangeDetector",
    "ChangeReport",
    "SEVERITY_ORDER",
    "render_change_report_json",
    "render_change_report_markdown",
]
