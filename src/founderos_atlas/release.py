"""The single authoritative release identity for FounderOS Atlas.

Everything that displays or records a version derives from this module:
package metadata (pyproject.toml reads ``VERSION`` via setuptools
``attr:``), the Settings page, diagnostics, update information, the CLI,
backup manifests, report stamps, and startup logs. Change the version
HERE and nowhere else — a second literal anywhere is a bug.

The module is deliberately import-light (stdlib only, no package
imports) so setuptools can resolve ``VERSION`` statically at build time
and any layer can import it without side effects.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

PRODUCT_NAME = "FounderOS Atlas"

# Canonical PEP 440 version — the one source of truth.
VERSION = "0.3.0a1"

# The human-facing form used by Settings, backups, and reports.
DISPLAY_VERSION = f"{PRODUCT_NAME} {VERSION}"

# PR-180 §4: "0.3.0a1" is a Python packaging convention — a network
# engineer does not read "a1" as pre-release. Detection is an ANCHORED
# PEP 440 test over the release segment (local build metadata after
# "+" stripped first): a naive substring scan would label 0.3.0.dev1 a
# finished release and 1.0.0+build.5 a pre-release. The one word shown
# is "Beta" — never "channel", which implies update infrastructure
# Atlas deliberately does not have.
def is_prerelease(version: str) -> bool:
    return bool(
        re.search(r"(?:(?:a|b|rc)\d+|\.dev\d+)$", version.split("+")[0])
    )


IS_PRERELEASE = is_prerelease(VERSION)

# The one line of product identity the chrome carries — DISPLAY_VERSION
# plus the Beta token. NEVER the commit hash: a commit pins an exact
# source tree rather than a release, and belongs only on the
# system.admin Settings card, the update page, diagnostics and the CLI.
IDENTITY_LINE = f"{DISPLAY_VERSION} · Beta" if IS_PRERELEASE else DISPLAY_VERSION


# PR-180 §30 Step 0: the value is INTENTIONALLY frozen at first call.
# `register_observability` (web/observability.py) primes this at
# startup — before any request is served — so the cached identifier
# describes the bytes the process actually loaded, not whatever HEAD
# points at after a later `git pull`. A test pins that priming order;
# do not remove the startup call or this cache without re-weighing
# that honesty property. (Uncached, this was also a measured ~47 ms
# subprocess paid twice per /settings render.)
@lru_cache(maxsize=1)
def build_commit() -> str | None:
    """The build identifier, or None when none can be PROVEN.

    PR-180 §3 trust rule: Atlas prints a build identifier only when it
    can prove the identifier describes the running bytes. A hash from a
    dirty tree describes code the process may never have run; a hash
    from a repository that merely CONTAINS an installed Atlas describes
    someone else's project entirely. Both are worse than no identifier
    — a missing value announces its own absence, a wrong value
    announces confidence — so both resolve to None, and every surface
    renders the one causeless sentence "not available in this build".

    Resolution order (the packaging seam, not packaging itself):
    1. ``ATLAS_BUILD_ID`` — a packaged build injects its identity via
       the environment;
    2. ``founderos_atlas._build_id`` — a build step may generate this
       module with a ``BUILD_ID`` constant;
    3. a git derivation trusted only when the tree is clean
       (``describe --dirty`` has no suffix) AND the repository is this
       package's own (this very file is tracked by it);
    4. None.

    Best-effort and side-effect-free: this never raises into the
    caller.
    """

    injected = os.environ.get("ATLAS_BUILD_ID", "").strip()
    if injected:
        return injected
    generated = _generated_build_id()
    if generated:
        return generated
    return _git_identifier()


def _generated_build_id() -> str | None:
    """The BUILD_ID a packaging step generated into the package."""

    try:
        from founderos_atlas import _build_id  # type: ignore[attr-defined]
    except ImportError:
        return None
    value = str(getattr(_build_id, "BUILD_ID", "") or "").strip()
    return value or None


def _git_identifier() -> str | None:
    """A git identifier, only when it provably describes this code."""

    repo = Path(__file__).resolve().parents[2]
    if not (repo / ".git").exists():
        return None
    described = _run_git(repo, "describe", "--always", "--dirty")
    if described is None or described.endswith("-dirty"):
        # A dirty tree: the commit does not describe the running bytes.
        return None
    try:
        mine = Path(__file__).resolve().relative_to(repo).as_posix()
    except ValueError:  # pragma: no cover - resolve() moved us outside
        return None
    if _run_git(repo, "ls-files", "--error-unmatch", mine) is None:
        # The repository two levels up is NOT this package's — an Atlas
        # installed inside another project's checkout must not report
        # that project's HEAD as its own build.
        return None
    return described


def _run_git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
