"""Bounded, deterministic manifest discovery for one Workspace root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from founderos_runtime.manifest_loader import ManifestLoader

from .exceptions import WorkspaceDiscoveryError


DIRECTORY_KINDS = {
    "agents": "agent",
    "workflows": "workflow",
    "apps": "app",
}


@dataclass(frozen=True)
class DiscoveredManifest:
    kind: str
    path: Path
    data: dict[str, Any]


def _kind_for_path(path: Path, root: Path) -> str | None:
    relative_parts = path.relative_to(root).parts[:-1]
    for part in reversed(relative_parts):
        kind = DIRECTORY_KINDS.get(part.lower())
        if kind is not None:
            return kind
    return None


def discover_manifests(root: Path, loader: ManifestLoader) -> tuple[DiscoveredManifest, ...]:
    """Load supported YAML manifests beneath a resolved, non-symlink Workspace root."""

    if not root.exists():
        raise WorkspaceDiscoveryError(f"workspace root does not exist: {root}")
    if not root.is_dir():
        raise WorkspaceDiscoveryError(f"workspace root is not a directory: {root}")
    if root.is_symlink():
        raise WorkspaceDiscoveryError(f"workspace root must not be a symbolic link: {root}")

    resolved_root = root.resolve()
    candidates = sorted(
        (path for pattern in ("*.yaml", "*.yml") for path in root.rglob(pattern)),
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        ),
    )
    discovered: list[DiscoveredManifest] = []
    seen_paths: set[Path] = set()

    for path in candidates:
        if path.is_symlink():
            raise WorkspaceDiscoveryError(f"manifest path must not be a symbolic link: {path}")
        if not path.is_file():
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as error:
            raise WorkspaceDiscoveryError(f"manifest escapes workspace root: {path}") from error
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)

        kind = _kind_for_path(path, root)
        if kind is None:
            continue
        if kind == "agent":
            data = loader.load_agent_manifest(path)
        elif kind == "workflow":
            data = loader.load_workflow_manifest(path)
        else:
            data = loader.load_app_manifest(path)
        discovered.append(DiscoveredManifest(kind=kind, path=path, data=data))
    return tuple(discovered)
