"""Typed Workspace loading and query failures."""

from __future__ import annotations


class WorkspaceError(Exception):
    """Base class for deterministic Workspace failures."""


class WorkspaceDiscoveryError(WorkspaceError):
    """The requested Workspace root or a discovered path is unsafe or invalid."""


class WorkspaceDuplicateIdError(WorkspaceError):
    """Two manifests declare the same logical identifier."""

    def __init__(self, kind: str, identifier: str, first_path: str, duplicate_path: str) -> None:
        self.kind = kind
        self.identifier = identifier
        self.first_path = first_path
        self.duplicate_path = duplicate_path
        super().__init__(
            f"duplicate {kind} id {identifier!r}: {first_path} and {duplicate_path}"
        )


class WorkspaceMissingReferenceError(WorkspaceError):
    """A manifest references an unavailable exact definition or dependency."""


class WorkspaceCompatibilityError(WorkspaceError):
    """A definition or dependency is incompatible with the Workspace runtime."""


class WorkspaceDependencyCycleError(WorkspaceError):
    """App dependencies contain a cycle."""


class WorkspaceItemNotFoundError(WorkspaceError):
    """A query requested an identifier not present in the Workspace."""
