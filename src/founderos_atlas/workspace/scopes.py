"""Profile-scoped discovery workspaces (PR-031A).

Each discovery profile owns an isolated workspace directory — its own
current artifacts, configuration snapshots, and discovery history — so a
discovery run for one profile can never overwrite, or be compared against,
another profile's network. The scope identifier is the profile's stable
``profile_id`` (never the display name), so renaming a profile keeps all
of its history.

Layout (relative to the base output directory):

    <base>/                                # default scope: legacy layout,
        topology_snapshot.json, ...        # used by profile-less discovery
        .atlas/history/
        .atlas/profiles/<profile_id>/      # one scope per profile
            topology_snapshot.json, ...
            configs/
            history/

Legacy data recorded before profile scoping existed stays in the default
scope. It is never reassigned to a profile: Atlas cannot know which network
produced it, so guessing would corrupt history.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_SCOPE_ID = "default"
DEFAULT_SCOPE_LABEL = "Local workspace"
GLOBAL_SCOPE_ID = "all"
# PR-041 (POLISH): enterprise-first language. The id stays "all" for
# backward compatibility (URLs, sessions, stored reports); the label a
# user sees is the enterprise.
GLOBAL_SCOPE_LABEL = "Enterprise"

PROFILE_SCOPES_SUBDIR = Path(".atlas") / "profiles"
SCOPE_HISTORY_DIRNAME = "history"


@dataclass(frozen=True)
class DiscoveryScope:
    """One isolated discovery workspace: where a network's data lives."""

    scope_id: str
    label: str
    output_dir: Path
    history_root: Path

    @property
    def is_default(self) -> bool:
        return self.scope_id == DEFAULT_SCOPE_ID

    def artifact(self, name: str) -> Path:
        return self.output_dir / name

    @property
    def snapshot_path(self) -> Path:
        return self.output_dir / "topology_snapshot.json"

    def has_data(self) -> bool:
        """True when this scope holds a current topology or any history."""

        if self.snapshot_path.is_file():
            return True
        root = self.history_root
        return root.is_dir() and any(entry.is_dir() for entry in root.iterdir())


def default_scope(
    output_dir: str | Path, history_root: str | Path | None = None
) -> DiscoveryScope:
    """The legacy/unscoped workspace: today's fixed CWD-relative layout."""

    out = Path(output_dir)
    history = Path(history_root) if history_root is not None else out / ".atlas" / "history"
    return DiscoveryScope(
        scope_id=DEFAULT_SCOPE_ID,
        label=DEFAULT_SCOPE_LABEL,
        output_dir=out,
        history_root=history,
    )


def profile_scope(
    base_output_dir: str | Path, profile_id: str, profile_name: str | None = None
) -> DiscoveryScope:
    """The isolated workspace owned by one profile, keyed by its stable id."""

    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")
    root = Path(base_output_dir) / PROFILE_SCOPES_SUBDIR / profile_id
    return DiscoveryScope(
        scope_id=profile_id,
        label=profile_name or profile_id,
        output_dir=root,
        history_root=root / SCOPE_HISTORY_DIRNAME,
    )


def profile_scopes(
    base_output_dir: str | Path, profiles
) -> tuple[DiscoveryScope, ...]:
    """One scope per saved profile, in the profiles' given order."""

    return tuple(
        profile_scope(base_output_dir, profile.profile_id, profile.name)
        for profile in profiles
    )


def active_scopes(
    default: DiscoveryScope, profiles
) -> tuple[DiscoveryScope, ...]:
    """The scopes that make up the current network estate (All Networks).

    Legacy-data policy (PR-031A): profile scopes that have completed a
    discovery are authoritative. The default (legacy/unscoped) scope
    participates in aggregation only while NO profile scope holds data —
    so pre-scoping installations keep a working All Networks view, but once
    explicit profiles have discovered, stale legacy artifacts can no longer
    duplicate devices, inflate counts, or degrade aggregated health. Legacy
    data is never deleted and stays fully accessible by selecting the
    default scope directly.
    """

    discovered = tuple(scope for scope in profiles if scope.has_data())
    if discovered:
        return discovered
    return (default,) if default.has_data() else ()
