"""Classify configuration section changes into networking categories.

Ordered prefix rules map a section to a category; a documented category
map assigns severity. Rules are data, not code branches — new categories
extend the tables without touching the algorithm.
"""

from __future__ import annotations

from .diff import SECTION_ADDED, SECTION_REMOVED, SectionDiff, diff_sections
from .models import (
    CATEGORY_AAA,
    CATEGORY_ACLS,
    CATEGORY_BGP,
    CATEGORY_INTERFACES,
    CATEGORY_LINE_ACCESS,
    CATEGORY_LOGGING,
    CATEGORY_NAT,
    CATEGORY_NTP,
    CATEGORY_OSPF,
    CATEGORY_OTHER,
    CATEGORY_ROUTING,
    CATEGORY_SNMP,
    CATEGORY_STATIC_ROUTES,
    CATEGORY_VLANS,
    ConfigChange,
    ConfigChangeReport,
)


# Ordered: first prefix match wins (specific before general).
_CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("interface ", CATEGORY_INTERFACES),
    ("router ospf", CATEGORY_OSPF),
    ("router bgp", CATEGORY_BGP),
    ("router ", CATEGORY_ROUTING),
    ("ip route", CATEGORY_STATIC_ROUTES),
    ("ipv6 route", CATEGORY_STATIC_ROUTES),
    ("vlan", CATEGORY_VLANS),
    ("ip access-list", CATEGORY_ACLS),
    ("access-list", CATEGORY_ACLS),
    ("ip nat", CATEGORY_NAT),
    ("logging", CATEGORY_LOGGING),
    ("snmp-server", CATEGORY_SNMP),
    ("ntp", CATEGORY_NTP),
    ("aaa", CATEGORY_AAA),
    ("username", CATEGORY_AAA),
    ("enable", CATEGORY_AAA),
    ("tacacs", CATEGORY_AAA),
    ("radius", CATEGORY_AAA),
    ("line vty", CATEGORY_LINE_ACCESS),
    ("line con", CATEGORY_LINE_ACCESS),
    ("line aux", CATEGORY_LINE_ACCESS),
)

_CATEGORY_SEVERITY: dict[str, str] = {
    CATEGORY_ACLS: "high",
    CATEGORY_NAT: "high",
    CATEGORY_AAA: "high",
    CATEGORY_LINE_ACCESS: "high",
    CATEGORY_BGP: "high",
    CATEGORY_OSPF: "medium",
    CATEGORY_ROUTING: "medium",
    CATEGORY_STATIC_ROUTES: "medium",
    CATEGORY_INTERFACES: "medium",
    CATEGORY_VLANS: "medium",
    CATEGORY_SNMP: "medium",
    CATEGORY_LOGGING: "low",
    CATEGORY_NTP: "low",
    CATEGORY_OTHER: "low",
}

_CATEGORY_RECOMMENDATIONS: dict[str, str] = {
    CATEGORY_INTERFACES: "Verify the interface change was planned and check link state on both ends.",
    CATEGORY_OSPF: "Verify OSPF adjacencies and route tables after this change.",
    CATEGORY_BGP: "Verify BGP sessions and received/advertised prefixes; routing policy changes can be wide-reaching.",
    CATEGORY_ROUTING: "Verify routing protocol adjacencies and convergence after this change.",
    CATEGORY_STATIC_ROUTES: "Confirm the static route change matches the intended traffic path.",
    CATEGORY_VLANS: "Confirm VLAN changes are propagated consistently across switches.",
    CATEGORY_ACLS: "Review the access-list change against security policy; verify permitted and denied traffic.",
    CATEGORY_NAT: "Verify NAT translations and reachability for affected services.",
    CATEGORY_LOGGING: "Confirm logging destinations still receive events.",
    CATEGORY_SNMP: "Verify monitoring continuity and that SNMP access remains restricted.",
    CATEGORY_NTP: "Verify time synchronization; inconsistent clocks corrupt log correlation.",
    CATEGORY_AAA: "Review the authentication change immediately; verify device access before ending the session.",
    CATEGORY_LINE_ACCESS: "Review console/VTY access changes immediately; verify remote access still works and remains restricted.",
    CATEGORY_OTHER: "Review this configuration change and record its intent.",
}


def categorize(classification_header: str) -> str:
    header = classification_header.strip().casefold()
    for prefix, category in _CATEGORY_RULES:
        if header.startswith(prefix):
            return category
    return CATEGORY_OTHER


def classify_section(diff: SectionDiff, hostname: str) -> ConfigChange:
    category = categorize(diff.classification_header or diff.header)
    severity = _CATEGORY_SEVERITY[category]
    if category == CATEGORY_INTERFACES and _touches_shutdown(diff):
        severity = "high"
    if diff.kind == SECTION_ADDED:
        action = "was added"
    elif diff.kind == SECTION_REMOVED:
        action = "was removed"
    else:
        action = "changed"
    summary = (
        f"{hostname}: {diff.header} {action} "
        f"({len(diff.added_lines)} added, {len(diff.removed_lines)} removed line(s))"
    )
    return ConfigChange(
        hostname=hostname,
        category=category,
        severity=severity,
        summary=summary,
        recommendation=_CATEGORY_RECOMMENDATIONS[category],
        added_lines=diff.added_lines,
        removed_lines=diff.removed_lines,
        raw_diff_reference=diff.header,
    )


def compare_configurations(
    previous_text: str,
    current_text: str,
    *,
    hostname: str = "device",
    previous_ref: str = "previous",
    current_ref: str = "current",
) -> ConfigChangeReport:
    """Diff, classify, and package two configurations into a report."""

    if not isinstance(previous_text, str) or not isinstance(current_text, str):
        raise TypeError("configurations must be text")
    changes = tuple(
        classify_section(diff, hostname)
        for diff in diff_sections(previous_text, current_text)
    )
    return ConfigChangeReport(
        hostname=hostname,
        previous_ref=previous_ref,
        current_ref=current_ref,
        changes=changes,
    )


def _touches_shutdown(diff: SectionDiff) -> bool:
    return any(
        line.strip() in ("shutdown", "no shutdown")
        for line in (*diff.added_lines, *diff.removed_lines)
    )
