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
from functools import lru_cache
from pathlib import Path

PRODUCT_NAME = "FounderOS Atlas"

# Canonical PEP 440 version — the one source of truth.
VERSION = "0.3.0a1"

# The human-facing form used by Settings, backups, and reports.
DISPLAY_VERSION = f"{PRODUCT_NAME} {VERSION}"


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
