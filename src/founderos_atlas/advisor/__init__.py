"""Atlas Advisor (PR-042): the conversational interface to Atlas.

Advisor is NOT an AI chatbot. It is an evidence ORCHESTRATION layer:
a deterministic intent router classifies every question onto an
existing engine (search, federation, path intelligence, prediction,
Compass, discovery history, change intelligence), the handler performs
REAL work through that engine, and the response follows one fixed
structure — Summary, Evidence (openable), Confidence, Recommended Next
Action, Follow-ups — plus the steps actually performed.

Advisor never invents facts, never replaces the deterministic engines,
and says "I don't currently have enough evidence." when it cannot
answer. The engineer always remains in control; Mission remains the
operational home.
"""

from .engine import AdvisorContext, answer
from .models import (
    ADVISOR_SCHEMA_VERSION,
    AdvisorResponse,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
    EvidenceItem,
    FollowUp,
    NO_EVIDENCE_MESSAGE,
    confidence_from_band,
)
from .router import (
    INTENT_CHANGES,
    INTENT_COMPASS,
    INTENT_CONTINUE,
    INTENT_DISCOVERY,
    INTENT_ENTERPRISE,
    INTENT_HEALTH,
    INTENT_INVESTIGATION,
    INTENT_PATH,
    INTENT_PREDICTION,
    INTENT_SEARCH,
    INTENT_UNKNOWN,
    classify,
    discovery_launch,
    path_endpoints,
    prediction_target,
    search_query,
)
from .service import ConversationRepository, advisor_dir, ask

__all__ = [
    "ADVISOR_SCHEMA_VERSION",
    "AdvisorContext",
    "AdvisorResponse",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_UNKNOWN",
    "ConversationRepository",
    "EvidenceItem",
    "FollowUp",
    "INTENT_CHANGES",
    "INTENT_COMPASS",
    "INTENT_CONTINUE",
    "INTENT_DISCOVERY",
    "INTENT_ENTERPRISE",
    "INTENT_HEALTH",
    "INTENT_INVESTIGATION",
    "INTENT_PATH",
    "INTENT_PREDICTION",
    "INTENT_SEARCH",
    "INTENT_UNKNOWN",
    "NO_EVIDENCE_MESSAGE",
    "advisor_dir",
    "answer",
    "ask",
    "classify",
    "confidence_from_band",
    "discovery_launch",
    "path_endpoints",
    "prediction_target",
    "search_query",
]
