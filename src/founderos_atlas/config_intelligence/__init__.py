"""Configuration intelligence: classified, secret-masked config comparison."""

from .classifier import categorize, classify_section, compare_configurations
from .diff import (
    SENSITIVE_TERMS,
    SectionDiff,
    diff_sections,
    mask_line,
    parse_sections,
)
from .models import SEVERITY_ORDER, ConfigChange, ConfigChangeReport
from .report import render_config_report_json, render_config_report_markdown

__all__ = [
    "ConfigChange",
    "ConfigChangeReport",
    "SENSITIVE_TERMS",
    "SEVERITY_ORDER",
    "SectionDiff",
    "categorize",
    "classify_section",
    "compare_configurations",
    "diff_sections",
    "mask_line",
    "parse_sections",
    "render_config_report_json",
    "render_config_report_markdown",
]
