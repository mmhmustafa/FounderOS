"""Atlas Path Intelligence (PR-037, codename FLOW).

Investigate end-to-end connectivity the way a senior engineer would —
without SSH-ing into five devices. Given a source and destination device,
Atlas constructs the known path from discovered evidence, validates every
hop (device, interfaces, operational state, link, management reachability),
stops at the first deterministic failure, explains WHY with cited
evidence, and recommends the next action.

Deterministic only: no packet simulation, no traceroute, no AI. Ambiguous
topology is reported as ambiguity — never guessed through. Missing
evidence is stated, and confidence is banded and capped below 100%.
"""

from .engine import investigate_path
from .models import (
    HOP_FAILED,
    HOP_PASS,
    HOP_UNKNOWN,
    HOP_WARNING,
    HopResult,
    InvestigationStep,
    PathInvestigationResult,
)
from .service import (
    investigate_path_for_scope,
    load_investigation_history,
    render_investigation_json,
    render_investigation_markdown,
)

__all__ = [
    "HOP_FAILED",
    "HOP_PASS",
    "HOP_UNKNOWN",
    "HOP_WARNING",
    "HopResult",
    "InvestigationStep",
    "PathInvestigationResult",
    "investigate_path",
    "investigate_path_for_scope",
    "load_investigation_history",
    "render_investigation_json",
    "render_investigation_markdown",
]
