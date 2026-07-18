"""Evidence-backed runtime facts for Settings and diagnostics."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from founderos_atlas.release import DISPLAY_VERSION, VERSION, build_commit
from founderos_atlas.workspace.migrations import (
    CURRENT_SCHEMA_VERSION,
    applied_version,
)
from founderos_atlas.workspace.update_info import update_information


def collect_system_information(app, *, credential_provider, preferences) -> dict[str, Any]:
    root = app.config["ATLAS_WORKSPACE_ROOT"]
    provider_available = _provider_available(credential_provider)
    auth_mode = str(app.config.get("ATLAS_AUTH_MODE") or "local")
    tls_enabled = bool(app.config.get("ATLAS_TLS", False))
    sessions = app.config.get("ATLAS_SESSION_STORE")
    trusted = tuple(app.config.get("ATLAS_TRUSTED_PROXY_ADDRS") or ())
    host = str(app.config.get("ATLAS_HOST") or "unknown")
    port = app.config.get("ATLAS_PORT")
    manager = app.config.get("ATLAS_JOB_MANAGER")
    jobs = manager.list_recent(limit=100) if manager is not None else []
    active_jobs = sum(1 for item in jobs if item.get("status") in {"queued", "running"})
    update = update_information(root)

    if auth_mode == "password":
        session_mode = "server-side opaque sessions (SHA-256 token hashes at rest)"
        session_expiry = _session_expiry(sessions)
    elif auth_mode == "proxy":
        session_mode = "identity asserted per request by the trusted SSO proxy"
        session_expiry = "controlled by the external identity proxy; Atlas stores no proxy session"
    else:
        session_mode = "loopback-only process-local development principal"
        session_expiry = "no login session; access ends when the local process/request ends"

    bind_value = f"{host}:{port}" if port is not None else host
    bind_observation = (
        "Atlas application bind; external proxy/listener binding is not observable "
        "from this process."
        if auth_mode == "proxy"
        else "Atlas application bind configured for this process."
    )
    logger = app.config.get("ATLAS_LOGGER")
    log_level = logging.getLevelName(
        logger.level if logger is not None else app.logger.getEffectiveLevel()
    )
    applied = applied_version(root)

    return {
        "product": "FounderOS Atlas",
        "version": VERSION,
        "display_version": DISPLAY_VERSION,
        "build_commit": build_commit(),
        "authentication_mode": auth_mode,
        "credential_provider": _provider_name(credential_provider),
        "credential_provider_class": type(credential_provider).__name__,
        "credential_provider_available": provider_available,
        "tls_enabled": tls_enabled,
        "hsts_enabled": tls_enabled,
        "bind": bind_value,
        "bind_observation": bind_observation,
        "trusted_proxies": list(trusted),
        "session_mode": session_mode,
        "session_expiry": session_expiry,
        "worker_model": "one process per workspace; in-process discovery threads",
        "worker_status": f"available; {active_jobs} active discovery job(s)",
        "workspace_schema_version": applied,
        "workspace_schema_target": CURRENT_SCHEMA_VERSION,
        "logging_level": str(log_level),
        "retention_policy": (
            f"{preferences.retention_days} days; manual audited preview/execute, "
            "no scheduled deletion worker"
        ),
        "update_provider": update["update_provider"],
    }


def _provider_available(provider) -> bool:
    try:
        return bool(provider.available())
    except Exception:
        return False


def _provider_name(provider) -> str:
    names = {
        "KeyringCredentialProvider": "OS keyring",
        "EncryptedFileCredentialProvider": "AES-256-GCM encrypted file",
        "InMemoryCredentialProvider": "in-memory (non-persistent; test/development only)",
    }
    return names.get(type(provider).__name__, type(provider).__name__)


def _session_expiry(store) -> str:
    if store is None:
        return "unavailable"
    return (
        f"absolute {_duration(store.max_age)}; idle {_duration(store.idle_timeout)}; "
        "sliding idle deadline"
    )


def _duration(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"
