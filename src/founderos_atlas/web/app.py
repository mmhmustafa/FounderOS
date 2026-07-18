"""Flask application factory for the Atlas web application.

Atlas runs in one of three authentication modes (``ATLAS_AUTH_MODE``):

- ``local`` (default): the historical single-operator development mode.
  Binds to 127.0.0.1 and refuses non-loopback clients outright.
- ``password``: production mode — user store, server-side sessions,
  RBAC, CSRF tokens, and full audit attribution.
- ``proxy``: production mode behind an SSO-terminating reverse proxy.

Security, authorization, health probes, and structured logging are wired
by ``register_security`` / ``register_ops_routes`` /
``register_observability`` at the bottom of ``create_app``. The backend
services run in-process — the same objects the CLI uses.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from founderos_atlas.console import (
    ConsoleAuditLog,
    ConsoleSessionManager,
    ConsoleTokenStore,
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_DURATION_SECONDS,
)
from founderos_atlas.transport import DeviceTransport
from founderos_atlas.workspace import (
    ProfileService,
    ProfileRepository,
    default_workspace_root,
    resolve_credential_provider,
)

from .jobs import DiscoveryJobManager
from .timefmt import AUTO
from .routes import make_pipeline_runner, register_routes


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

TransportFactory = Callable[[object], DeviceTransport]
Clock = Callable[[], datetime]


def create_app(
    *,
    profile_service: ProfileService | None = None,
    output_dir: str | Path | None = None,
    history_root: str | Path | None = None,
    transport_factory: TransportFactory | None = None,
    clock: Clock | None = None,
    workspace_root: str | Path | None = None,
    job_manager: DiscoveryJobManager | None = None,
    auth_mode: str | None = None,
):
    """Build the Atlas Flask app with injectable backend services.

    ``transport_factory`` and ``clock`` are injected in tests so discovery can
    run against a scripted network with deterministic timestamps; in normal
    operation they default to real SSH and the wall clock.
    """

    try:
        from flask import Flask
    except ImportError as error:  # pragma: no cover - exercised via CLI
        raise RuntimeError(
            "The Atlas web GUI requires Flask. Install it with: "
            "pip install founderos-runtime[web]"
        ) from error

    package_root = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(package_root / "templates"),
        static_folder=str(package_root / "static"),
    )

    resolved_output = Path(output_dir).resolve() if output_dir is not None else Path.cwd()
    resolved_output.mkdir(parents=True, exist_ok=True)
    resolved_history = (
        Path(history_root)
        if history_root is not None
        else resolved_output / ".atlas" / "history"
    )
    resolved_workspace = (
        Path(workspace_root) if workspace_root is not None else default_workspace_root()
    )
    if profile_service is None:
        profile_service = ProfileService(
            ProfileRepository(resolved_workspace),
            resolve_credential_provider(),
            clock=clock,
        )

    app.config.update(
        ATLAS_PROFILE_SERVICE=profile_service,
        ATLAS_OUTPUT_DIR=resolved_output,
        ATLAS_HISTORY_ROOT=resolved_history,
        ATLAS_WORKSPACE_ROOT=resolved_workspace,
        ATLAS_TRANSPORT_FACTORY=transport_factory,
        ATLAS_CLOCK=clock,
        ATLAS_HOST=os.environ.get("ATLAS_HOST", DEFAULT_HOST),
        ATLAS_PORT=int(os.environ.get("ATLAS_PORT", DEFAULT_PORT)),
        ATLAS_LOG_LEVEL=os.environ.get("ATLAS_LOG_LEVEL", "INFO"),
        # Display only. Every stored timestamp stays UTC; this decides the
        # zone the GUI renders them in. "auto" = the local operator's own
        # system clock; "UTC" or an IANA name (e.g. "Asia/Kolkata")
        # overrides it — NOC teams often standardise on UTC to correlate
        # against device syslog.
        ATLAS_DISPLAY_TIMEZONE=os.environ.get("ATLAS_DISPLAY_TIMEZONE", AUTO),
    )

    # PR-044A (CONSOLE). Interactive SSH is the one place the GUI stops being
    # read-only, so its limits are explicit and its origin rule is strict.
    app.config.update(
        ATLAS_CONSOLE_TOKENS=ConsoleTokenStore(clock=clock),
        ATLAS_CONSOLE_SESSIONS=ConsoleSessionManager(
            audit=ConsoleAuditLog(resolved_output / ".atlas" / "console-audit.jsonl"),
            idle_timeout_seconds=int(
                os.environ.get(
                    "ATLAS_CONSOLE_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT_SECONDS
                )
            ),
            max_duration_seconds=int(
                os.environ.get(
                    "ATLAS_CONSOLE_MAX_DURATION", DEFAULT_MAX_DURATION_SECONDS
                )
            ),
            max_concurrent=int(
                os.environ.get("ATLAS_CONSOLE_MAX_SESSIONS", DEFAULT_MAX_CONCURRENT)
            ),
            clock=clock,
        ),
        ATLAS_CONSOLE_CONNECT_TIMEOUT=float(
            os.environ.get("ATLAS_CONSOLE_CONNECT_TIMEOUT", 10.0)
        ),
        # Extra Origins the console WebSocket will accept. The GUI's own
        # address is always allowed; this exists for a reverse proxy, and
        # should stay empty otherwise. Never set it to "*" — a WebSocket has
        # no CORS to fall back on.
        ATLAS_CONSOLE_ALLOWED_ORIGINS=tuple(
            item.strip()
            for item in os.environ.get("ATLAS_CONSOLE_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        ),
    )
    # The signing key is set by register_security (random per process
    # unless ATLAS_SECRET_KEY is provided); server-side sessions do not
    # depend on it.

    # Shared formatting: `{{ value | timestamp }}` renders any stored UTC
    # ISO-8601 timestamp in the operator's display timezone (see timefmt);
    # non-timestamp values pass through unchanged. templates/_fmt.html wraps
    # this in a <time> element that preserves the precise instant.
    from .timefmt import format_timestamp as _format_timestamp, resolve_timezone

    def _timestamp_filter(value):
        return _format_timestamp(
            value, tz=resolve_timezone(app.config.get("ATLAS_DISPLAY_TIMEZONE"))
        )

    app.add_template_filter(_timestamp_filter, "timestamp")

    if job_manager is None:
        # In-process background executor for GUI discoveries. Job history
        # persists under the output dir so interrupted runs are marked
        # honestly after a restart; the interface allows a production job
        # backend to replace it later.
        def _notify_discovery_failure(job) -> None:
            from founderos_atlas.notifications import (
                KIND_DISCOVERY_FAILED,
                NotificationStore,
            )

            NotificationStore(resolved_workspace).notify(
                kind=KIND_DISCOVERY_FAILED,
                title=f"Discovery failed for {job.profile_name}",
                detail=str(job.error or "See the job log."),
                href="/discovery",
                audience="role:network-operator",
                dedupe_key=f"discovery-failed:{job.profile_id}",
            )

        job_manager = DiscoveryJobManager(
            runner=make_pipeline_runner(app),
            profile_service=profile_service,
            persist_path=resolved_output / ".atlas" / "jobs.json",
            on_failure=_notify_discovery_failure,
        )
    app.config["ATLAS_JOB_MANAGER"] = job_manager

    # Enforce the supported concurrency model: ONE process per workspace.
    # A second process (extra WSGI worker, stray server) fails here with
    # instructions instead of silently racing shared files.
    from founderos_atlas.workspace.instance import acquire_instance_lock

    app.config["ATLAS_INSTANCE_LOCK"] = acquire_instance_lock(
        resolved_workspace
    )

    # Ordered, backed-up schema migrations run before anything reads the
    # workspace; each is idempotent and audited.
    from founderos_atlas.workspace.migrations import migrate_workspace

    migrate_workspace(resolved_workspace)

    from .models import NAV_GROUPS

    @app.context_processor
    def _navigation_defaults():
        """Every page gets the workflow sidebar, even when its route does
        not pass the full base context — /users once rendered with an
        empty navigation pane exactly because its render call forgot it.
        Explicit render arguments always override these defaults, so
        pages that DO pass base_context keep their active highlighting.
        """

        try:
            from founderos_atlas.workspace.administration import (
                AdministrationRepository,
            )

            preferences = AdministrationRepository(
                app.config["ATLAS_WORKSPACE_ROOT"]
            ).preferences()
        except Exception:
            preferences = None
        return {
            "nav_groups": NAV_GROUPS,
            "active": "",
            "active_group": "",
            "product": "Atlas",
            "ui_theme": preferences.theme if preferences else "system",
            "ui_density": (
                preferences.density if preferences else "comfortable"
            ),
        }

    register_routes(app)

    # Authentication, authorization, CSRF, rate limits, security headers,
    # safe error pages, health probes, and structured request logging.
    from .observability import register_observability
    from .ops import register_ops_routes
    from .security import register_security

    register_security(app, auth_mode=auth_mode)
    register_ops_routes(app)
    register_observability(app)
    return app
