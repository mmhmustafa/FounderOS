"""Installed policy packs.

A pack is data (:class:`~founderos_atlas.policy.models.PolicyPack`). Installing a
future pack — Cisco Enterprise, CIS, STIG, PCI-DSS, a customer's own (Part 6) —
means adding a module here and registering it below. The engine never changes.
"""

from __future__ import annotations

from ..models import PolicyPack
from .starter import STARTER_PACK

# The registry of packs Atlas knows. Ordered; the first is the default.
INSTALLED_PACKS: tuple[PolicyPack, ...] = (STARTER_PACK,)

_BY_ID = {pack.pack_id: pack for pack in INSTALLED_PACKS}


def default_pack() -> PolicyPack:
    return INSTALLED_PACKS[0]


def get_pack(pack_id: str) -> PolicyPack | None:
    return _BY_ID.get(pack_id)


def list_packs() -> tuple[PolicyPack, ...]:
    return INSTALLED_PACKS


__all__ = ["INSTALLED_PACKS", "STARTER_PACK", "default_pack", "get_pack", "list_packs"]
