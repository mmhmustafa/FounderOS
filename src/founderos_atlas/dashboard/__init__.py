"""Atlas executive dashboard: deterministic operational summary rendering."""

from .renderer import DashboardRenderer
from .summary import (
    DashboardAction,
    DashboardSummary,
    GlobalDashboardSummary,
    NetworkSummary,
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_UNKNOWN,
    STATUS_WARNING,
    aggregate_dashboard_summaries,
    build_dashboard_summary,
)

__all__ = [
    "DashboardAction",
    "DashboardRenderer",
    "DashboardSummary",
    "GlobalDashboardSummary",
    "NetworkSummary",
    "STATUS_CRITICAL",
    "STATUS_HEALTHY",
    "STATUS_UNKNOWN",
    "STATUS_WARNING",
    "aggregate_dashboard_summaries",
    "build_dashboard_summary",
]
