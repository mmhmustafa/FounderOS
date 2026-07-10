"""Flask application factory for the local Atlas GUI shell.

This is a **local, single-user alpha GUI** — not a production or multi-user
web deployment. It binds to 127.0.0.1 by default, has no authentication, and
runs the same in-process backend services the CLI uses (never a subprocess).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from founderos_atlas.transport import DeviceTransport
from founderos_atlas.workspace import (
    ProfileService,
    ProfileRepository,
    default_workspace_root,
    resolve_credential_provider,
)

from .jobs import DiscoveryJobManager
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
        ATLAS_HOST=DEFAULT_HOST,
    )
    app.secret_key = "atlas-local-alpha"  # only used for flash messages, local-only

    if job_manager is None:
        # In-process background executor for GUI discoveries. Job history
        # persists under the output dir so interrupted runs are marked
        # honestly after a restart; the interface allows a production job
        # backend to replace it later.
        job_manager = DiscoveryJobManager(
            runner=make_pipeline_runner(app),
            profile_service=profile_service,
            persist_path=resolved_output / ".atlas" / "jobs.json",
        )
    app.config["ATLAS_JOB_MANAGER"] = job_manager

    register_routes(app)
    return app
