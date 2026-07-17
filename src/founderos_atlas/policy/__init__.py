"""Enterprise Policy Engine (SENTINEL, PR-047).

Atlas's first application built entirely on CORTEX — the Phase-5 acceptance gate
for the reasoning framework (``docs/architecture/REASONING_ENGINE.md`` §12).
Atlas does not hard-code compliance; it *evaluates policies*. Compliance is one
policy pack; Security, CIS, STIG, PCI, and customer packs are more data over the
same, unchanged reasoning engine.

Public surface:

- :class:`~founderos_atlas.policy.models.Policy` / ``PolicyPack`` — the model
- :class:`~founderos_atlas.policy.engine.PolicyEngine` — the evaluation pipeline
- :class:`~founderos_atlas.policy.models.PolicyReport` — the aggregated result
- :data:`~founderos_atlas.policy.packs.STARTER_PACK` — the first pack
"""

from __future__ import annotations

from .engine import PolicyEngine
from .matcher import MATCH_REGEX, MATCH_SUBSTRING, OPERATORS, MatchReport, PolicyCheck
from .models import (
    CATEGORIES,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_UNKNOWN,
    STATUS_WARNING,
    Policy,
    PolicyEvaluation,
    PolicyPack,
    PolicyReport,
)
from .packs import INSTALLED_PACKS, STARTER_PACK, default_pack, get_pack, list_packs
from .rule import PolicyRule

__all__ = [
    "PolicyEngine",
    "Policy",
    "PolicyPack",
    "PolicyEvaluation",
    "PolicyReport",
    "PolicyCheck",
    "PolicyRule",
    "MatchReport",
    "CATEGORIES",
    "OPERATORS",
    "MATCH_REGEX",
    "MATCH_SUBSTRING",
    "STATUS_PASSED",
    "STATUS_FAILED",
    "STATUS_WARNING",
    "STATUS_UNKNOWN",
    "INSTALLED_PACKS",
    "STARTER_PACK",
    "default_pack",
    "get_pack",
    "list_packs",
]
