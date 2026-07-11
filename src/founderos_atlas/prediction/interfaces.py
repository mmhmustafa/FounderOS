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

# Interface type classification (PR-036C). Names come from discovery, so
# classifying by canonical name IS evidence-based; anything unmatched is
# honestly "unknown" rather than forced into a category.
TYPE_PHYSICAL = "physical"
TYPE_SVI = "svi"
TYPE_LOOPBACK = "loopback"
TYPE_TUNNEL = "tunnel"
TYPE_PORT_CHANNEL = "port-channel"
TYPE_SUBINTERFACE = "subinterface"
TYPE_UNKNOWN = "unknown"

LOGICAL_TYPES = (TYPE_SVI, TYPE_LOOPBACK, TYPE_TUNNEL, TYPE_PORT_CHANNEL)

_PHYSICAL_PREFIXES = (
    "ethernet", "fastethernet", "gigabitethernet", "tengigabitethernet",
    "twentyfivegige", "fortygigabitethernet", "hundredgige", "serial",
    "management",
)


def classify_interface(name: str) -> str:
    """Deterministic interface type from the canonical discovered name."""

    cleaned = (name or "").strip().casefold()
    if not cleaned:
        return TYPE_UNKNOWN
    if cleaned.startswith("vlan"):
        return TYPE_SVI
    if cleaned.startswith("loopback"):
        return TYPE_LOOPBACK
    if cleaned.startswith("tunnel"):
        return TYPE_TUNNEL
    if cleaned.startswith("port-channel") or cleaned.startswith("po"):
        # "po" alone is ambiguous with nothing else in Cisco naming; the
        # canonical inventory names are full words, so this stays safe.
        if cleaned.startswith("port-channel"):
            return TYPE_PORT_CHANNEL
    for prefix in _PHYSICAL_PREFIXES:
        if cleaned.startswith(prefix):
            return TYPE_SUBINTERFACE if "." in cleaned else TYPE_PHYSICAL
    return TYPE_UNKNOWN


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
