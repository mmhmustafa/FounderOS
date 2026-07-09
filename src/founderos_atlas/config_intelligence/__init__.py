"""Configuration intelligence: classified, secret-masked config comparison."""

from .classifier import categorize, classify_section, compare_configurations
from .diff import (
    CISCO_DYNAMIC_METADATA_PATTERNS,
    SENSITIVE_TERMS,
    SectionDiff,
    diff_sections,
    is_dynamic_metadata,
    mask_line,
    parse_sections,
)
from .models import SEVERITY_ORDER, ConfigChange, ConfigChangeReport
from .report import render_config_report_json, render_config_report_markdown

__all__ = [
    "CISCO_DYNAMIC_METADATA_PATTERNS",
    "ConfigChange",
    "ConfigChangeReport",
    "SENSITIVE_TERMS",
    "SEVERITY_ORDER",
    "SectionDiff",
    "categorize",
    "classify_section",
    "compare_configurations",
    "diff_sections",
    "is_dynamic_metadata",
    "mask_line",
    "parse_sections",
    "render_config_report_json",
    "render_config_report_markdown",
]
