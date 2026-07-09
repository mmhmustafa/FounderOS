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
from .service import ProfileService, ResolvedDiscoveryInputs

__all__ = [
    "AtlasWorkspaceError",
    "CredentialNotFoundError",
    "CredentialProvider",
    "CredentialStoreUnavailableError",
    "DiscoveryProfile",
    "DuplicateProfileError",
    "InMemoryCredentialProvider",
    "InvalidProfileError",
    "KeyringCredentialProvider",
    "ProfileNotFoundError",
    "ProfileRepository",
    "ProfileService",
    "ResolvedDiscoveryInputs",
    "WorkspaceCorruptedError",
    "atlas_home",
    "credential_ref_for",
    "default_workspace_root",
    "profile_id_for",
    "resolve_credential_provider",
]
