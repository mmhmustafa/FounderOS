"""Canonical device identity resolution for Atlas."""

from .canonical import (
    CanonicalDevice,
    DeviceIdentity,
    RECOGNIZED_IDENTIFIER_KEYS,
    choose_primary_hostname,
    display_label,
    is_bare_hostname,
    normalize_hostname,
    short_hostname,
)
from .matching import (
    DEFAULT_MATCH_RULES,
    ExtraIdentifierMatch,
    HostnameMatch,
    ManagementIPMatch,
    MatchRule,
    SerialNumberMatch,
)
from .resolver import IdentityResolution, IdentityResolver
from .resolutions import (
    PeerIdentityResolution,
    PeerResolutionCatalog,
    PeerResolutionConflictError,
    PeerResolutionEvent,
    PeerResolutionRepository,
    peer_subject_key,
    resolution_candidates,
)

__all__ = [
    "PeerIdentityResolution",
    "PeerResolutionCatalog",
    "PeerResolutionConflictError",
    "PeerResolutionEvent",
    "PeerResolutionRepository",
    "peer_subject_key",
    "resolution_candidates",
    "CanonicalDevice",
    "DEFAULT_MATCH_RULES",
    "DeviceIdentity",
    "ExtraIdentifierMatch",
    "HostnameMatch",
    "IdentityResolution",
    "IdentityResolver",
    "ManagementIPMatch",
    "MatchRule",
    "RECOGNIZED_IDENTIFIER_KEYS",
    "SerialNumberMatch",
    "choose_primary_hostname",
    "display_label",
    "is_bare_hostname",
    "normalize_hostname",
    "short_hostname",
]
