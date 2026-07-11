"""Canonical interface resolution with deterministic alias handling.

Users think in CLI shorthand (``Gi0/1``); Atlas artifacts store canonical
names (``GigabitEthernet0/1``). This layer resolves user input against a
device's *discovered* interface inventory:

- exact (case-insensitive) matches win;
- an alias resolves when its alphabetic prefix unambiguously starts one
  available interface type with the same number suffix
  (``Gi0/1`` / ``Gig0/1`` -> ``GigabitEthernet0/1``);
- an ambiguous alias (``T0/1`` with both ``TenGigabitEthernet0/1`` and
  ``Tunnel0/1`` discovered) is REJECTED with both candidates named —
  Atlas never guesses;
- anything else is rejected with a clean reason.

Resolution only ever selects from the provided inventory, so an interface
belonging to another device can never resolve.
"""

from __future__ import annotations

import re


_NAME_PATTERN = re.compile(r"^([A-Za-z][A-Za-z-]*)\s*([0-9][0-9/\.:]*)$")


def resolve_interface(
    requested: str, available: tuple[str, ...] | list[str]
) -> tuple[str | None, str | None]:
    """Resolve user input to one canonical discovered interface.

    Returns ``(canonical, None)`` on success or ``(None, reason)`` on
    rejection. Deterministic: identical inputs always resolve identically.
    """

    cleaned = (requested or "").strip()
    if not cleaned:
        return None, "an interface name is required"
    inventory = [str(name) for name in available]
    if not inventory:
        return None, "no discovered interfaces are available"

    for name in inventory:
        if name.casefold() == cleaned.casefold():
            return name, None  # exact match, canonical casing from inventory

    match = _NAME_PATTERN.match(cleaned)
    if match is None:
        return None, (
            f"{cleaned!r} is not a recognizable interface name"
        )
    prefix, suffix = match.group(1).casefold(), match.group(2)
    candidates = sorted(
        name
        for name in inventory
        if (parsed := _NAME_PATTERN.match(name)) is not None
        and parsed.group(2) == suffix
        and parsed.group(1).casefold().startswith(prefix)
    )
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, (
            f"{cleaned!r} is ambiguous between {', '.join(candidates)}; "
            "use the full interface name"
        )
    return None, f"{cleaned!r} does not match any discovered interface"
