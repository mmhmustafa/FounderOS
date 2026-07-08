"""Atlas executive dashboard: deterministic operational summary rendering."""

from .renderer import DashboardRenderer
from .summary import (
    DashboardAction,
    DashboardSummary,
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_UNKNOWN,
    STATUS_WARNING,
    build_dashboard_summary,
)

__all__ = [
    "DashboardAction",
    "DashboardRenderer",
    "DashboardSummary",
    "STATUS_CRITICAL",
    "STATUS_HEALTHY",
    "STATUS_UNKNOWN",
    "STATUS_WARNING",
    "build_dashboard_summary",
]
