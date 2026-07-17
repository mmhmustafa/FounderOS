"""Typed failures for the Atlas workspace and profile system."""


class AtlasWorkspaceError(Exception):
    """Base failure for the Atlas workspace / profile system."""


class ProfileNotFoundError(AtlasWorkspaceError):
    """No saved profile matches the requested name."""


class DuplicateProfileError(AtlasWorkspaceError):
    """A profile with the same name already exists."""


class InvalidProfileError(AtlasWorkspaceError):
    """The profile data failed validation (name, IP, limits)."""


class WorkspaceCorruptedError(AtlasWorkspaceError):
    """The workspace metadata file could not be read as valid profile data."""


class CredentialStoreUnavailableError(AtlasWorkspaceError):
    """No secure credential store is available on this machine."""


class CredentialNotFoundError(AtlasWorkspaceError):
    """The secure credential for a profile could not be resolved."""


class ProfileConflictError(AtlasWorkspaceError):
    """The caller edited an older revision of the profile catalog."""
