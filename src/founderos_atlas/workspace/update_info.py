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
from pathlib import Path
from typing import Any

from founderos_atlas.release import VERSION, build_commit

PROVIDER_UNCONFIGURED = "unconfigured"
PROVIDER_UNAVAILABLE = "unavailable"
PROVIDER_OK = "ok"


def update_information(workspace_root: str | Path) -> dict[str, Any]:
    from .migrations import CURRENT_SCHEMA_VERSION, applied_version

    info: dict[str, Any] = {
        "application_version": VERSION,
        "build_commit": build_commit(),
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
