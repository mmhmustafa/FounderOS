"""Identity, authorization, sessions, and rate limiting for Atlas."""

from .models import (
    ALL_PERMISSIONS,
    ALL_ROLES,
    LOCAL_OPERATOR,
    Principal,
    ROLE_GRANTS,
    permissions_for,
)
from .providers import (
    AUTH_MODES,
    AuthDecision,
    LocalDevelopmentAuth,
    PasswordAuth,
    ProxySSOAuth,
    is_loopback,
    resolve_auth_mode,
)
from .ratelimit import RateLimiter
from .sessions import SESSION_COOKIE, SessionRecord, SessionStore
from .users import (
    UserAccount,
    UserConflictError,
    UserStore,
    UserStoreError,
    hash_password,
    verify_password,
)

__all__ = [
    "ALL_PERMISSIONS", "ALL_ROLES", "AUTH_MODES", "AuthDecision",
    "LOCAL_OPERATOR", "LocalDevelopmentAuth", "PasswordAuth", "Principal",
    "ProxySSOAuth", "ROLE_GRANTS", "RateLimiter", "SESSION_COOKIE",
    "SessionRecord", "SessionStore", "UserAccount", "UserConflictError",
    "UserStore", "UserStoreError", "hash_password", "is_loopback",
    "permissions_for", "resolve_auth_mode", "verify_password",
]
