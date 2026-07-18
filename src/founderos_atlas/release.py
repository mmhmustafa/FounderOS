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

import subprocess
from pathlib import Path

PRODUCT_NAME = "FounderOS Atlas"

# Canonical PEP 440 version — the one source of truth.
VERSION = "0.3.0a1"

# The human-facing form used by Settings, backups, and reports.
DISPLAY_VERSION = f"{PRODUCT_NAME} {VERSION}"


def build_commit() -> str | None:
    """The short git commit if running from a checkout, else None.

    Best-effort and side-effect-free: installed (non-checkout)
    deployments simply have no observable commit, and this never raises
    into the caller.
    """

    repo = Path(__file__).resolve().parents[2]
    if not (repo / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None
