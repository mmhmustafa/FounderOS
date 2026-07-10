"""HTTP routes for the Atlas GUI. Thin adapters over existing services.

No route contains profile, discovery, or credential business logic — every
handler calls a backend service (ProfileService, the discovery pipeline,
HistoryRepository, the dashboard summary, the incident investigator). No
route ever spawns a CLI process; the pipeline is invoked in-process.

Every data page is scope-aware (PR-031A): the user picks an active network
scope — one discovery profile, the local unscoped workspace, or All
Networks. A profile scope reads only that profile's isolated workspace;
All Networks aggregates the latest state of every scope without ever
comparing one network against another.
"""

from __future__ import annotations

from pathlib import Path

from founderos_atlas.dashboard import (
    NetworkSummary,
    aggregate_dashboard_summaries,
    build_dashboard_summary,
)
from founderos_atlas.history import HistoryRepository, generate_timeline
from founderos_atlas.incidents import (
    IncidentArtifacts,
    IncidentInvestigator,
    render_incident_report_json,
    render_incident_report_markdown,
)
from founderos_atlas.workspace import (
    AtlasWorkspaceError,
    DEFAULT_SCOPE_ID,
    DEFAULT_SCOPE_LABEL,
    DiscoveryScope,
    GLOBAL_SCOPE_ID,
    GLOBAL_SCOPE_LABEL,
    active_scopes,
    default_scope,
    profile_scope,
    resolve_credential_provider,
)

from .models import (
    NAV_ITEMS,
    change_summaries,
    device_inventory,
    history_rows,
    load_json,
    profile_row,
)


def register_routes(app) -> None:
    from flask import (
        abort,
        flash,
        redirect,
        render_template,
        request,
        send_from_directory,
        session,
        url_for,
    )

    def cfg(key: str):
        return app.config[key]

    def output_dir() -> Path:
        return cfg("ATLAS_OUTPUT_DIR")

    def profile_service():
        return cfg("ATLAS_PROFILE_SERVICE")

    def base_context(active: str) -> dict:
        return {"nav_items": NAV_ITEMS, "active": active, "product": "Atlas"}

    # -- Scopes ---------------------------------------------------------------

    def known_scopes() -> dict[str, DiscoveryScope]:
        """Every selectable scope: one per profile plus the local workspace."""

        scopes: dict[str, DiscoveryScope] = {}
        for profile in profile_service().list_profiles():
            scope = profile_scope(output_dir(), profile.profile_id, profile.name)
            scopes[scope.scope_id] = scope
        scopes[DEFAULT_SCOPE_ID] = default_scope(
            output_dir(), cfg("ATLAS_HISTORY_ROOT")
        )
        return scopes

    def active_scope_id(scopes: dict[str, DiscoveryScope]) -> str:
        """Resolve the selected scope: ?scope= wins, then session, then All."""

        requested = request.args.get("scope", "").strip()
        if requested == GLOBAL_SCOPE_ID or requested in scopes:
            session["scope"] = requested
            return requested
        saved = session.get("scope")
        if saved == GLOBAL_SCOPE_ID or saved in scopes:
            return saved
        return GLOBAL_SCOPE_ID

    def artifact_prefix(scope: DiscoveryScope) -> str:
        """URL path prefix under /artifacts/ where this scope's files live."""

        if scope.is_default:
            return ""
        return f".atlas/profiles/{scope.scope_id}/"

    def aggregation_scopes(
        scopes: dict[str, DiscoveryScope],
    ) -> tuple[DiscoveryScope, ...]:
        """The scopes All Networks aggregates — see the legacy-data policy
        on ``active_scopes``: once profile scopes hold discovery data, the
        legacy Local workspace no longer participates (it stays selectable)."""

        return active_scopes(
            scopes[DEFAULT_SCOPE_ID],
            tuple(
                scope for key, scope in scopes.items() if key != DEFAULT_SCOPE_ID
            ),
        )

    def scoped_context(active: str) -> tuple[dict, dict[str, DiscoveryScope], str]:
        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        options = [{"id": GLOBAL_SCOPE_ID, "label": GLOBAL_SCOPE_LABEL}]
        options.extend(
            {"id": key, "label": scope.label}
            for key, scope in scopes.items()
            if key != DEFAULT_SCOPE_ID
        )
        local = scopes[DEFAULT_SCOPE_ID]
        if local.has_data() or scope_id == DEFAULT_SCOPE_ID:
            local_label = DEFAULT_SCOPE_LABEL
            if any(
                scope.has_data()
                for key, scope in scopes.items()
                if key != DEFAULT_SCOPE_ID
            ):
                # Superseded by profile-scoped discoveries: archived, not active.
                local_label += " (legacy)"
            options.append({"id": DEFAULT_SCOPE_ID, "label": local_label})
        label = (
            GLOBAL_SCOPE_LABEL
            if scope_id == GLOBAL_SCOPE_ID
            else scopes[scope_id].label
        )
        context = {
            **base_context(active),
            "scope_selector": options,
            "active_scope_id": scope_id,
            "active_scope_label": label,
        }
        return context, scopes, scope_id

    def summary_for(scope: DiscoveryScope):
        out = scope.output_dir
        return build_dashboard_summary(
            snapshot_path=out / "topology_snapshot.json",
            topology_path=out / "atlas_topology.html",
            brief_path=out / "morning_brief.md",
            change_report_json=out / "change_report.json",
            change_report_md=out / "change_report.md",
            configs_dir=out / "configs",
            history_root=scope.history_root,
            timeline_path=out / "timeline.md",
            config_change_report=out / "config_change_report.json",
            config_change_report_md=out / "config_change_report.md",
            state_change_report=out / "state_change_report.json",
            state_change_report_md=out / "state_change_report.md",
            incident_report=out / "incident_report.json",
            incident_report_md=out / "incident_report.md",
            link_base=out,
        )

    def merged_history_rows(scopes) -> tuple[list[dict], tuple[str, ...]]:
        rows: list[dict] = []
        issues: list[str] = []
        for scope in scopes:
            index = HistoryRepository(scope.history_root).load()
            rows.extend(history_rows(index, scope_label=scope.label))
            issues.extend(f"{scope.label}: {issue}" for issue in index.issues)
        rows.sort(key=lambda row: row["started_at_iso"], reverse=True)
        return rows, tuple(issues)

    # -- Dashboard ----------------------------------------------------------

    @app.route("/")
    def dashboard():
        context, scopes, scope_id = scoped_context("dashboard")
        if scope_id == GLOBAL_SCOPE_ID:
            aggregated = aggregation_scopes(scopes)
            networks = tuple(
                NetworkSummary(
                    scope_id=scope.scope_id,
                    label=scope.label,
                    summary=summary_for(scope),
                )
                for scope in aggregated
            )
            recent, _ = merged_history_rows(aggregated)
            return render_template(
                "dashboard_global.html",
                summary=aggregate_dashboard_summaries(networks),
                recent=recent[:8],
                **context,
            )
        scope = scopes[scope_id]
        return render_template(
            "dashboard.html",
            summary=summary_for(scope),
            artifact_prefix=artifact_prefix(scope),
            **context,
        )

    # -- Profiles -----------------------------------------------------------

    @app.route("/profiles")
    def profiles():
        rows = [profile_row(p) for p in profile_service().list_profiles()]
        return render_template("profiles.html", profiles=rows, **base_context("profiles"))

    @app.route("/profiles/new")
    def profile_new():
        return render_template(
            "profile_form.html", mode="add", profile=None, **base_context("profiles")
        )

    @app.route("/profiles", methods=["POST"])
    def profile_create():
        form = request.form
        try:
            profile_service().add_profile(
                name=form.get("name", "").strip(),
                site=(form.get("site", "").strip() or None),
                management_ip=form.get("management_ip", "").strip(),
                username=form.get("username", "").strip(),
                password=form.get("password", ""),
                max_depth=_int(form.get("max_depth"), 1),
                max_devices=_int(form.get("max_devices"), 10),
                collect_configuration=form.get("collect_configuration") == "on",
            )
        except (AtlasWorkspaceError, ValueError) as error:
            flash(str(error), "error")
            return render_template(
                "profile_form.html", mode="add", profile=None, **base_context("profiles")
            )
        flash("Profile saved.", "success")
        return redirect(url_for("profiles"))

    @app.route("/profiles/<name>/edit")
    def profile_edit(name: str):
        try:
            profile = profile_service().get_profile(name)
        except AtlasWorkspaceError:
            abort(404)
        return render_template(
            "profile_form.html",
            mode="edit",
            profile=profile_row(profile),
            **base_context("profiles"),
        )

    @app.route("/profiles/<name>", methods=["POST"])
    def profile_update(name: str):
        form = request.form
        try:
            profile_service().update_profile(
                name,
                new_name=(form.get("name", "").strip() or None),
                management_ip=(form.get("management_ip", "").strip() or None),
                username=(form.get("username", "").strip() or None),
                password=(form.get("password") or None),
                site=(form.get("site", "").strip() or None),
                max_depth=_int(form.get("max_depth"), None),
                max_devices=_int(form.get("max_devices"), None),
                collect_configuration=form.get("collect_configuration") == "on",
            )
        except (AtlasWorkspaceError, ValueError) as error:
            flash(str(error), "error")
            return redirect(url_for("profile_edit", name=name))
        flash("Profile updated.", "success")
        return redirect(url_for("profiles"))

    @app.route("/profiles/<name>/delete", methods=["POST"])
    def profile_delete(name: str):
        try:
            profile_service().delete_profile(name)
            flash("Profile deleted.", "success")
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
        return redirect(url_for("profiles"))

    # -- Discovery ----------------------------------------------------------

    @app.route("/discovery")
    def discovery():
        rows = [profile_row(p) for p in profile_service().list_profiles()]
        return render_template(
            "discovery.html", profiles=rows, result=None, **base_context("discovery")
        )

    @app.route("/discovery/run", methods=["POST"])
    def discovery_run():
        name = request.form.get("profile", "").strip()
        rows = [profile_row(p) for p in profile_service().list_profiles()]
        if not name:
            flash("Select a saved profile to run discovery.", "error")
            return render_template(
                "discovery.html", profiles=rows, result=None, **base_context("discovery")
            )
        result = _run_discovery(app, name)
        if result["ok"]:
            # Focus the GUI on the network that was just discovered.
            try:
                session["scope"] = profile_service().get_profile(name).profile_id
            except AtlasWorkspaceError:
                pass
        return render_template(
            "discovery.html",
            profiles=rows,
            result=result,
            selected=name,
            **base_context("discovery"),
        )

    # -- Topology / History / Changes --------------------------------------

    @app.route("/topology")
    def topology():
        context, scopes, scope_id = scoped_context("topology")
        if scope_id == GLOBAL_SCOPE_ID:
            with_data = [
                scope
                for scope in aggregation_scopes(scopes)
                if scope.snapshot_path.is_file()
            ]
            inventory = device_inventory(
                (scope.label, load_json(scope.snapshot_path)) for scope in with_data
            )
            viewers = [
                {
                    "label": scope.label,
                    "scope_id": scope.scope_id,
                    "href": f"/artifacts/{artifact_prefix(scope)}atlas_topology.html",
                }
                for scope in with_data
                if (scope.output_dir / "atlas_topology.html").is_file()
            ]
            return render_template(
                "topology.html",
                global_view=True,
                inventory=inventory,
                viewers=viewers,
                has_topology=False,
                **context,
            )
        scope = scopes[scope_id]
        exists = (scope.output_dir / "atlas_topology.html").is_file()
        return render_template(
            "topology.html",
            global_view=False,
            has_topology=exists,
            topology_src=f"/artifacts/{artifact_prefix(scope)}atlas_topology.html",
            **context,
        )

    @app.route("/history")
    def history():
        context, scopes, scope_id = scoped_context("history")
        if scope_id == GLOBAL_SCOPE_ID:
            records, issues = merged_history_rows(aggregation_scopes(scopes))
            return render_template(
                "history.html",
                records=records,
                issues=issues,
                show_profile=True,
                **context,
            )
        scope = scopes[scope_id]
        index = HistoryRepository(scope.history_root).load()
        return render_template(
            "history.html",
            records=history_rows(index, scope_label=scope.label),
            issues=index.issues,
            show_profile=False,
            **context,
        )

    @app.route("/changes")
    def changes():
        context, scopes, scope_id = scoped_context("changes")
        if scope_id == GLOBAL_SCOPE_ID:
            networks = [
                {
                    "label": scope.label,
                    "scope_id": scope.scope_id,
                    "summaries": change_summaries(scope.output_dir),
                    "artifact_prefix": artifact_prefix(scope),
                }
                for scope in aggregation_scopes(scopes)
            ]
            return render_template(
                "changes.html",
                global_view=True,
                networks=networks,
                summaries=None,
                **context,
            )
        scope = scopes[scope_id]
        return render_template(
            "changes.html",
            global_view=False,
            summaries=change_summaries(scope.output_dir),
            artifact_prefix=artifact_prefix(scope),
            **context,
        )

    # -- Incidents ----------------------------------------------------------

    @app.route("/incidents")
    def incidents():
        context, scopes, scope_id = scoped_context("incidents")
        if scope_id == GLOBAL_SCOPE_ID:
            reports = [
                {
                    "label": scope.label,
                    "report": load_json(scope.output_dir / "incident_report.json"),
                    "href": f"/artifacts/{artifact_prefix(scope)}incident_report.md",
                }
                for scope in aggregation_scopes(scopes)
                if (scope.output_dir / "incident_report.json").is_file()
            ]
            return render_template(
                "incidents.html",
                global_view=True,
                reports=reports,
                report=None,
                **context,
            )
        scope = scopes[scope_id]
        report = load_json(scope.output_dir / "incident_report.json")
        return render_template(
            "incidents.html",
            global_view=False,
            report=report,
            artifact_prefix=artifact_prefix(scope),
            **context,
        )

    @app.route("/incidents/run", methods=["POST"])
    def incidents_run():
        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        if scope_id == GLOBAL_SCOPE_ID:
            flash(
                "Select a specific network scope to run an investigation.", "error"
            )
            return redirect(url_for("incidents"))
        scope = scopes[scope_id]
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("An incident title is required.", "error")
            return redirect(url_for("incidents"))
        out = scope.output_dir
        artifacts = IncidentArtifacts.load(
            snapshot_path=out / "topology_snapshot.json",
            change_report_json=out / "change_report.json",
            config_change_report=out / "config_change_report.json",
            brief_path=out / "morning_brief.md",
            configs_dir=out / "configs",
            history_root=scope.history_root,
        )
        clock = cfg("ATLAS_CLOCK")
        generated_at = clock().isoformat(timespec="seconds") if clock else "unrecorded"
        report = IncidentInvestigator().investigate(
            title, description, artifacts, generated_at=generated_at
        )
        out.mkdir(parents=True, exist_ok=True)
        (out / "incident_report.json").write_text(
            render_incident_report_json(report), encoding="utf-8"
        )
        (out / "incident_report.md").write_text(
            render_incident_report_markdown(report), encoding="utf-8"
        )
        flash("Incident investigation generated.", "success")
        return redirect(url_for("incidents"))

    # -- Settings -----------------------------------------------------------

    @app.route("/settings")
    def settings():
        provider = resolve_credential_provider()
        try:
            available = provider.available()
        except Exception:  # pragma: no cover - defensive
            available = False
        context = {
            "workspace_root": str(cfg("ATLAS_WORKSPACE_ROOT")),
            "output_dir": str(output_dir()),
            "history_root": str(cfg("ATLAS_HISTORY_ROOT")),
            "credential_provider": type(provider).__name__,
            "credential_available": available,
            "bind_host": cfg("ATLAS_HOST"),
            "atlas_version": "FounderOS v0.3 Alpha",
        }
        return render_template("settings.html", **context, **base_context("settings"))

    # -- Artifact serving ---------------------------------------------------

    @app.route("/artifacts/<path:name>")
    def artifacts(name: str):
        return send_from_directory(str(output_dir()), name)


def _int(value, default):
    if value is None or str(value).strip() == "":
        return default
    return int(value)


def _run_discovery(app, profile_name: str) -> dict:
    """Run the existing unified discovery pipeline in-process for a profile.

    The pipeline itself scopes every artifact and the history baseline into
    the profile's isolated workspace, so this run can never overwrite or be
    compared against another profile's network.
    """

    from founderos_runtime.cli.commands import atlas_discover_command
    from founderos_runtime.cli.exceptions import CliError

    out = app.config["ATLAS_OUTPUT_DIR"]
    lines: list[str] = []
    try:
        code, _ = atlas_discover_command(
            profile=profile_name,
            profile_service=app.config["ATLAS_PROFILE_SERVICE"],
            transport_factory=app.config["ATLAS_TRANSPORT_FACTORY"],
            clock=app.config["ATLAS_CLOCK"],
            topology_output=out / "atlas_topology.html",
            snapshot_output=out / "topology_snapshot.json",
            brief_output=out / "morning_brief.md",
            config_output_dir=out / "configs",
            dashboard_output=out / "dashboard.html",
            history_root=app.config["ATLAS_HISTORY_ROOT"],
            change_report_json_output=out / "change_report.json",
            change_report_markdown_output=out / "change_report.md",
            config_change_json_output=out / "config_change_report.json",
            config_change_markdown_output=out / "config_change_report.md",
            state_change_json_output=out / "state_change_report.json",
            state_change_markdown_output=out / "state_change_report.md",
            browser_opener=lambda uri: None,
            progress=lines.append,
        )
    except CliError as error:
        return {"ok": False, "profile": profile_name, "error": str(error), "log": lines}
    return {"ok": code == 0, "profile": profile_name, "error": None, "log": lines}
