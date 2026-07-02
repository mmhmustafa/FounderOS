"""Deterministic plan authorization without Approval or execution."""

from .decision import AuthorizationDecision, PolicyResult, thaw
from .engine import AUTHORIZATION_ENGINE_VERSION, AuthorizationEngine
from .exceptions import AuthorizationError
from .policies import HIGH_RISK_CAPABILITIES, KNOWN_CAPABILITIES, POLICY_ORDER

__all__ = [
    "AUTHORIZATION_ENGINE_VERSION",
    "AuthorizationDecision",
    "AuthorizationEngine",
    "AuthorizationError",
    "HIGH_RISK_CAPABILITIES",
    "KNOWN_CAPABILITIES",
    "POLICY_ORDER",
    "PolicyResult",
    "thaw",
]

