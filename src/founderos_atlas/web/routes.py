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

from founderos_atlas.credentials import (
    CredentialScope,
    CredentialSetRepository,
    CredentialSetService,
    CredentialSuccessMemory,
)
from founderos_atlas.dashboard import (
    NetworkSummary,
    aggregate_dashboard_summaries,
    build_dashboard_summary,
)
from founderos_atlas.discovery import BoundaryPolicy
from founderos_atlas.enterprise import build_enterprise_view
from founderos_atlas.history import HistoryRepository, generate_timeline
from founderos_atlas.sites import SiteCatalogRepository
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
    ProfileNotFoundError,
    active_scopes,
    default_scope,
    profile_scope,
    resolve_credential_provider,
)

from .models import (
    NAV_ITEMS,
    change_summaries,
    credential_set_rows,
    device_inventory,
    enterprise_device_rows,
    history_rows,
    load_json,
    profile_row,
)


def register_routes(app) -> None:
    from flask import (
        abort,
        flash,
        jsonify,
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
                description=(form.get("description", "").strip() or None),
                seeds=_csv(form.get("seeds")),
                boundary=_boundary_from_form(form),
                credential_sets=_csv(form.get("credential_sets")),
                site_hint=(form.get("site_hint", "").strip() or None),
                domain_hint=(form.get("domain_hint", "").strip() or None),
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
            boundary = _boundary_from_form(form)
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
                description=(form.get("description", "").strip() or None),
                seeds=_csv(form.get("seeds")),
                boundary=boundary,
                clear_boundary=boundary is None,
                credential_sets=_csv(form.get("credential_sets")),
                site_hint=(form.get("site_hint", "").strip() or None),
                domain_hint=(form.get("domain_hint", "").strip() or None),
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

    # -- Credential sets ------------------------------------------------------

    def credential_service() -> CredentialSetService:
        return CredentialSetService(
            CredentialSetRepository(cfg("ATLAS_WORKSPACE_ROOT")),
            profile_service().credential_provider,
        )

    @app.route("/credentials")
    def credentials():
        rows = credential_set_rows(credential_service().list_sets())
        return render_template(
            "credentials.html", credential_sets=rows, **base_context("credentials")
        )

    @app.route("/credentials", methods=["POST"])
    def credentials_add():
        form = request.form
        try:
            scope = CredentialScope(
                vendors=_csv(form.get("vendors")),
                platforms=_csv(form.get("platforms")),
                hostname_patterns=_csv(form.get("hostname_patterns")),
                cidrs=_csv(form.get("cidrs")),
                sites=_csv(form.get("sites")),
            )
            credential_service().add_entry(
                set_name=form.get("set_name", "").strip(),
                label=form.get("label", "").strip(),
                username=form.get("username", "").strip(),
                password=form.get("password", ""),
                priority=_int(form.get("priority"), 100),
                scope=scope,
            )
            flash("Credential saved securely.", "success")
        except (AtlasWorkspaceError, ValueError) as error:
            flash(str(error), "error")
        return redirect(url_for("credentials"))

    @app.route("/credentials/<set_id>/<entry_id>/delete", methods=["POST"])
    def credentials_delete(set_id: str, entry_id: str):
        credential_service().delete_entry(set_id, entry_id)
        flash("Credential deleted.", "success")
        return redirect(url_for("credentials"))

    # -- Discovery ----------------------------------------------------------

    def job_manager():
        return cfg("ATLAS_JOB_MANAGER")

    def discovery_rows() -> list[dict]:
        """Profiles enriched with each one's latest discovery-job status."""

        rows = [profile_row(p) for p in profile_service().list_profiles()]
        manager = job_manager()
        for row in rows:
            latest = manager.latest_for_profile(row["profile_id"])
            row["job_status"] = latest.status if latest is not None else "—"
        return rows

    def discovery_page(rows, *, result=None, selected: str | None = None):
        """The Discover page. When All Networks is active there is no
        implicit choice: the user explicitly selects the profile to run."""

        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        if selected is None and scope_id not in (GLOBAL_SCOPE_ID, DEFAULT_SCOPE_ID):
            selected = scopes[scope_id].label  # scope label == profile name
        job = None
        if selected:
            for row in rows:
                if row["name"] == selected:
                    latest = job_manager().latest_for_profile(row["profile_id"])
                    if latest is not None:
                        job = job_manager().snapshot(latest)
                    break
        return render_template(
            "discovery.html",
            profiles=rows,
            result=result,
            selected=selected,
            job=job,
            **base_context("discovery"),
        )

    @app.route("/discovery")
    def discovery():
        return discovery_page(discovery_rows())

    @app.route("/discovery/run", methods=["POST"])
    def discovery_run():
        """No-JS fallback: run through the same job manager, synchronously."""

        name = request.form.get("profile", "").strip()
        rows = discovery_rows()
        if not name:
            flash("Select a saved profile to run discovery.", "error")
            return discovery_page(rows)
        try:
            job, _ = job_manager().start(name)
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
            return discovery_page(rows)
        session["scope"] = job.profile_id
        finished = job_manager().wait(job.job_id)
        result = {
            "ok": finished.status == "completed",
            "profile": name,
            "error": finished.error,
            "log": list(finished.log),
        }
        return discovery_page(discovery_rows(), result=result, selected=name)

    # -- Discovery job API (polled by the Discover page) ---------------------

    @app.route("/api/discovery/jobs", methods=["POST"])
    def api_discovery_job_create():
        payload = request.get_json(silent=True) or request.form
        name = str(payload.get("profile") or "").strip()
        if not name:
            return (
                jsonify(
                    error=(
                        "Select a network profile to discover. All Networks "
                        "is a view — discovery always targets one profile."
                    )
                ),
                400,
            )
        try:
            job, created = job_manager().start(name)
        except ProfileNotFoundError as error:
            return jsonify(error=str(error)), 404
        except AtlasWorkspaceError as error:
            return jsonify(error=str(error)), 400
        # Focus the GUI on the network being discovered.
        session["scope"] = job.profile_id
        status = 202 if created else 409
        return jsonify(job=job_manager().snapshot(job), created=created), status

    @app.route("/api/discovery/jobs/<job_id>")
    def api_discovery_job_get(job_id: str):
        job = job_manager().get(job_id)
        if job is None:
            return jsonify(error="Unknown discovery job."), 404
        return jsonify(job=job_manager().snapshot(job))

    @app.route("/api/discovery/jobs")
    def api_discovery_job_list():
        return jsonify(jobs=job_manager().list_recent())

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
            viewers = [
                {
                    "label": scope.label,
                    "scope_id": scope.scope_id,
                    "href": f"/artifacts/{artifact_prefix(scope)}atlas_topology.html",
                }
                for scope in with_data
                if (scope.output_dir / "atlas_topology.html").is_file()
            ]
            if any(not scope.is_default for scope in with_data):
                # Enterprise view: canonical devices with site + provenance.
                topology_view = build_enterprise_view(
                    output_dir(),
                    profile_service().list_profiles(),
                    catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
                    credential_memory=CredentialSuccessMemory(
                        cfg("ATLAS_WORKSPACE_ROOT")
                    ),
                )
                rows = enterprise_device_rows(topology_view)
                site_options = sorted({row["site"] for row in rows})
                site_filter = request.args.get("site", "").strip()
                if site_filter:
                    rows = [row for row in rows if row["site"] == site_filter]
                return render_template(
                    "topology.html",
                    global_view=True,
                    enterprise=True,
                    inventory=rows,
                    site_options=site_options,
                    site_filter=site_filter,
                    viewers=viewers,
                    has_topology=False,
                    **context,
                )
            inventory = device_inventory(
                (scope.label, load_json(scope.snapshot_path)) for scope in with_data
            )
            return render_template(
                "topology.html",
                global_view=True,
                enterprise=False,
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


def _csv(value) -> tuple[str, ...]:
    """Comma/whitespace-separated form field -> tuple of clean tokens."""

    if not value:
        return ()
    return tuple(
        token.strip() for token in str(value).replace("\n", ",").split(",")
        if token.strip()
    )


def _boundary_from_form(form) -> BoundaryPolicy | None:
    include = _csv(form.get("include_cidrs"))
    exclude = _csv(form.get("exclude_cidrs"))
    deny = _csv(form.get("deny_hostnames"))
    if not (include or exclude or deny):
        return None
    return BoundaryPolicy(
        include_cidrs=include,
        exclude_cidrs=exclude,
        deny_hostnames=deny,
    )


def make_pipeline_runner(app):
    """The shared discovery service adapter for GUI jobs.

    Both the CLI and the GUI execute ``atlas_discover_command`` — one
    pipeline, one behavior. This factory only wires the app's injected
    dependencies into it: the profile service resolves credentials
    server-side, the transport factory is wrapped so the job layer sees
    every real device connection, and every artifact path stays under the
    app's output directory (the pipeline re-roots them into the profile's
    isolated scope). Everything runs in-process; no child process is ever
    spawned.
    """

    def run(profile_name: str, on_line, on_connect) -> dict:
        from founderos_runtime.cli.commands import atlas_discover_command

        from founderos_atlas.history import HistoryRepository
        from founderos_atlas.transport import SSHDeviceTransport
        from founderos_atlas.workspace import profile_scope

        base_factory = app.config["ATLAS_TRANSPORT_FACTORY"] or SSHDeviceTransport

        def tracking_factory(credentials):
            on_connect(credentials.host)
            return base_factory(credentials)

        out = app.config["ATLAS_OUTPUT_DIR"]
        atlas_discover_command(
            profile=profile_name,
            profile_service=app.config["ATLAS_PROFILE_SERVICE"],
            transport_factory=tracking_factory,
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
            progress=on_line,
        )
        # Summarize from the profile's own scope: the authoritative record
        # of what this run produced.
        profile = app.config["ATLAS_PROFILE_SERVICE"].get_profile(profile_name)
        scope = profile_scope(out, profile.profile_id, profile.name)
        record = HistoryRepository(scope.history_root).latest()
        if record is None:
            return {}
        return {
            "devices": record.device_count,
            "relationships": record.relationship_count,
            "configurations_collected": record.configured_device_count,
            "duration_seconds": record.duration_seconds,
            "network_status": record.network_status,
            "failed_devices": len(record.failures),
        }

    return run
