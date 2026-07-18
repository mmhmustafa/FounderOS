"""Honest update information.

Atlas reports what it can PROVE about itself — installed version, build
commit, workspace schema version — and the state of any configured
update provider. It never fabricates a "latest version": a latest
version is reported ONLY when an update provider is configured and
reachable, and Atlas never downloads or installs anything without an
explicit, separate, audited action (none ships by default — the update
provider is an adapter seam).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

APPLICATION_VERSION = "0.3-alpha"

PROVIDER_UNCONFIGURED = "unconfigured"
PROVIDER_UNAVAILABLE = "unavailable"
PROVIDER_OK = "ok"


def _build_commit() -> str | None:
    """The short git commit if this is a checkout, else None. Best-effort
    and side-effect-free; never raises into the caller."""

    repo = Path(__file__).resolve().parents[3]
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


def update_information(workspace_root: str | Path) -> dict[str, Any]:
    from .migrations import CURRENT_SCHEMA_VERSION, applied_version

    info: dict[str, Any] = {
        "application_version": APPLICATION_VERSION,
        "build_commit": _build_commit(),
        "schema_version": applied_version(workspace_root),
        "schema_target": CURRENT_SCHEMA_VERSION,
        "schema_current": applied_version(workspace_root) == CURRENT_SCHEMA_VERSION,
    }

    provider_url = os.environ.get("ATLAS_UPDATE_PROVIDER_URL", "").strip()
    if not provider_url:
        info["update_provider"] = {
            "state": PROVIDER_UNCONFIGURED,
            "detail": "No update provider is configured. Atlas does not "
                      "check for or install updates on its own; configure "
                      "ATLAS_UPDATE_PROVIDER_URL to enable version checks.",
            "latest_version": None,
            "release_notes_url": None,
        }
        return info

    # A provider is configured but Atlas ships no network fetch by design
    # (no silent outbound calls). Report the seam honestly as offline
    # until a deployment supplies a real adapter.
    info["update_provider"] = {
        "state": PROVIDER_UNAVAILABLE,
        "detail": "An update provider URL is configured, but this build "
                  "ships no update client — the provider integration is an "
                  "adapter seam. No version comparison was performed and "
                  "nothing was downloaded.",
        "latest_version": None,
        "release_notes_url": provider_url,
    }
    return info
