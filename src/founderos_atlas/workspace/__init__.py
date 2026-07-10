"""Atlas workspace: saved discovery profiles and secure credential storage."""

from .credentials import (
    CredentialProvider,
    InMemoryCredentialProvider,
    KeyringCredentialProvider,
    resolve_credential_provider,
)
from .exceptions import (
    AtlasWorkspaceError,
    CredentialNotFoundError,
    CredentialStoreUnavailableError,
    DuplicateProfileError,
    InvalidProfileError,
    ProfileNotFoundError,
    WorkspaceCorruptedError,
)
from .models import DiscoveryProfile, credential_ref_for, profile_id_for
from .repository import ProfileRepository, atlas_home, default_workspace_root
from .scopes import (
    DEFAULT_SCOPE_ID,
    DEFAULT_SCOPE_LABEL,
    GLOBAL_SCOPE_ID,
    GLOBAL_SCOPE_LABEL,
    DiscoveryScope,
    active_scopes,
    default_scope,
    profile_scope,
    profile_scopes,
)
from .service import ProfileService, ResolvedDiscoveryInputs

__all__ = [
    "AtlasWorkspaceError",
    "CredentialNotFoundError",
    "CredentialProvider",
    "CredentialStoreUnavailableError",
    "DEFAULT_SCOPE_ID",
    "DEFAULT_SCOPE_LABEL",
    "DiscoveryProfile",
    "DiscoveryScope",
    "DuplicateProfileError",
    "GLOBAL_SCOPE_ID",
    "GLOBAL_SCOPE_LABEL",
    "InMemoryCredentialProvider",
    "InvalidProfileError",
    "KeyringCredentialProvider",
    "ProfileNotFoundError",
    "ProfileRepository",
    "ProfileService",
    "ResolvedDiscoveryInputs",
    "WorkspaceCorruptedError",
    "active_scopes",
    "atlas_home",
    "credential_ref_for",
    "default_scope",
    "default_workspace_root",
    "profile_id_for",
    "profile_scope",
    "profile_scopes",
    "resolve_credential_provider",
]
