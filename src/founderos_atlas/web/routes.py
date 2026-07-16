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

from datetime import datetime, timezone
from types import SimpleNamespace
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
from founderos_atlas.federation import (
    enterprise_captured_configs,
    enterprise_failed_hosts,
    enterprise_scope_dir,
    enterprise_seed_addresses,
    get_enterprise_graph,
    get_enterprise_inventory,
    overall_freshness,
    write_enterprise_artifacts,
)
from founderos_atlas.history import HistoryRepository, generate_timeline
from founderos_atlas.search import SearchService, search_enterprise
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
    NAV_GROUPS,
    change_summaries,
    credential_set_rows,
    device_inventory,
    history_rows,
    load_json,
    nav_group_for,
    prediction_targets,
    profile_row,
    timeline_activity,
)


def register_routes(app) -> None:
    from flask import (
        abort,
        flash,
        g,
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
        # ``active`` is the view key a route already passed; the sidebar derives
        # which workflow to open from it, so no route had to change.
        return {
            "nav_groups": NAV_GROUPS,
            "active": active,
            "active_group": nav_group_for(active),
            "product": "Atlas",
        }

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

    ENTERPRISE_ARTIFACT_PREFIX = ".atlas/enterprise/"

    def now_iso() -> str:
        clock = cfg("ATLAS_CLOCK")
        return (clock() if clock else datetime.now(timezone.utc)).isoformat(
            timespec="seconds"
        )

    # PR-041 (performance): the enterprise graph is deterministic for a
    # given set of evidence files, so cache it behind the same fingerprint
    # the search index uses. Enterprise pages stop rebuilding the graph
    # and rewriting artifacts on every request; a discovery, prediction,
    # investigation, or plan change moves the fingerprint and the next
    # request rebuilds. Freshness flags still track the current clock.
    enterprise_cache: dict = {"fingerprint": None, "graph": None, "snapshot": None}

    def enterprise_world():
        """The federated enterprise graph + snapshot for the Enterprise
        scope — a cached VIEW over the isolated profile scopes, never a
        second source of truth. Returns ``(graph, snapshot_dict)``; the
        snapshot is None when no profile has discovered yet.
        """

        from dataclasses import replace as dc_replace

        from founderos_atlas.federation import (
            contribution_is_fresh,
            enterprise_evidence_fingerprint,
        )

        profiles = profile_service().list_profiles()
        fingerprint = enterprise_evidence_fingerprint(
            output_dir(), profiles, workspace_root=cfg("ATLAS_WORKSPACE_ROOT")
        )
        now = now_iso()
        if fingerprint != enterprise_cache["fingerprint"]:
            graph = get_enterprise_graph(
                output_dir(),
                profiles,
                catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
                credential_memory=CredentialSuccessMemory(
                    cfg("ATLAS_WORKSPACE_ROOT")
                ),
                now=now,
            )
            snapshot = (
                write_enterprise_artifacts(output_dir(), graph).to_dict()
                if graph.devices
                else None
            )
            enterprise_cache.update(
                fingerprint=fingerprint, graph=graph, snapshot=snapshot
            )
            return graph, snapshot
        # Same evidence: reuse the graph, but re-evaluate freshness
        # against the CURRENT clock — stale is a function of time.
        graph = enterprise_cache["graph"]
        graph = dc_replace(
            graph,
            contributions=tuple(
                dc_replace(
                    contribution,
                    fresh=contribution_is_fresh(contribution.observed_at, now),
                )
                for contribution in graph.contributions
            ),
        )
        enterprise_cache["graph"] = graph
        return graph, enterprise_cache["snapshot"]

    def profile_for_scope(scope_id: str):
        """The discovery profile that owns a scope id, or None."""

        for profile in profile_service().list_profiles(include_archived=True):
            scope = profile_scope(output_dir(), profile.profile_id, profile.name)
            if scope.scope_id == scope_id:
                return profile
        return None

    def scoped_world(scope_id: str):
        """The graph + snapshot for the selected scope (PR-043.9, Part 1).

        Scope is authoritative: at the Enterprise scope every consumer reads
        the federated graph; at a network scope they read ONLY that
        network's graph. A scoped world uses the profile's own snapshot —
        which carries the full Evidence Correlation and discovery-statistics
        metadata — so a scoped Advisor answer can never disagree with the
        scoped Mission, Topology, Investigation, or Prediction.
        Returns ``(graph, snapshot_dict, profiles)``."""

        if scope_id == GLOBAL_SCOPE_ID:
            graph, snapshot = enterprise_world()
            return graph, snapshot, profile_service().list_profiles()
        profile = profile_for_scope(scope_id)
        if profile is None:
            graph, snapshot = enterprise_world()
            return graph, snapshot, profile_service().list_profiles()
        # One network: build the graph from just this observation point and
        # read its own richer snapshot.
        graph = get_enterprise_graph(
            output_dir(),
            [profile],
            catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
            credential_memory=CredentialSuccessMemory(cfg("ATLAS_WORKSPACE_ROOT")),
            now=now_iso(),
        )
        scope = profile_scope(output_dir(), profile.profile_id, profile.name)
        snapshot = load_json(scope.snapshot_path)
        return graph, snapshot, (profile,)

    def network_resolution():
        """The Enterprise → Network → Profile view derived from evidence
        (PR-043.9, Part 6). Networks are clusters of observation points that
        share technical identity — serials, router IDs, loopbacks,
        addresses, topology — never the profile name."""

        from founderos_atlas.enterprise import (
            ObservationPoint,
            fingerprint_snapshot,
            resolve_networks,
        )

        observations = []
        for profile in profile_service().list_profiles():
            scope = profile_scope(output_dir(), profile.profile_id, profile.name)
            snapshot = load_json(scope.snapshot_path)
            if snapshot is None:
                continue
            observations.append(
                ObservationPoint(
                    profile_id=scope.scope_id,
                    profile_name=profile.name,
                    fingerprint=fingerprint_snapshot(
                        snapshot, seeds=profile.all_seeds
                    ),
                    archived=profile.archived,
                )
            )
        return resolve_networks(observations)

    def enterprise_context(graph) -> dict:
        """Federation facts every enterprise page displays."""

        resolution = network_resolution()
        return {
            "enterprise_contributions": [
                contribution.to_dict() for contribution in graph.contributions
            ],
            "enterprise_fresh": overall_freshness(graph.contributions),
            "enterprise_device_count": graph.device_count,
            "enterprise_observation_count": graph.observation_count,
            "enterprise_merged_count": graph.merged_device_count,
            # PR-043.9: Networks and duplicate candidates, evidence-derived.
            "enterprise_network_count": resolution.network_count,
            "enterprise_profile_count": resolution.profile_count,
            "enterprise_networks": [
                network.to_dict() for network in resolution.networks
            ],
            "enterprise_duplicate_candidates": [
                candidate.to_dict()
                for candidate in resolution.duplicate_candidates
            ],
            "enterprise_cross_profile_links": len(graph.cross_profile_links),
            "enterprise_boundaries": [
                {
                    "local": link.local_hostname,
                    "local_interface": link.local_interface,
                    "remote": link.remote_hostname,
                    "observed_by": list(link.observed_by),
                }
                for link in graph.boundaries
            ],
            "enterprise_unknowns": list(graph.unknowns),
        }

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
            intelligence_report=out / "intelligence_report.json",
            intelligence_report_md=out / "intelligence_report.md",
            root_cause_report=out / "root_cause_report.json",
            root_cause_report_md=out / "root_cause_report.md",
            prediction_report=out / "prediction_report.json",
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
            return mission_workspace(context, scopes)
        scope = scopes[scope_id]
        return render_template(
            "dashboard.html",
            summary=summary_for(scope),
            artifact_prefix=artifact_prefix(scope),
            **context,
        )

    def mission_workspace(context: dict, scopes: dict):
        """MISSION (PR-040): the workflow-oriented enterprise workspace.

        Pure orchestration — every card reads artifacts the existing
        engines already produced; no engine logic lives here and the
        engines remain authoritative.
        """

        from founderos_atlas.compass import PlanRepository
        from founderos_atlas.path_intelligence import load_investigation_history

        from .mission import (
            build_activity_stream,
            build_recommendations,
            describe_age,
            merge_recent,
            shape_investigations,
            shape_prediction,
        )

        aggregated = aggregation_scopes(scopes)
        networks = tuple(
            NetworkSummary(
                scope_id=scope.scope_id,
                label=scope.label,
                summary=summary_for(scope),
            )
            for scope in aggregated
        )
        summary = aggregate_dashboard_summaries(networks)
        recent, _ = merged_history_rows(aggregated)
        graph, _snapshot = enterprise_world()
        now = now_iso()

        # Compass plans (advisor state, straight from the repository).
        repository = PlanRepository(output_dir())
        plans = []
        draft_plan_count = 0
        for plan in repository.list_plans():
            _, assessment = repository.get(plan.plan_id)
            if plan.status != "analysed":
                draft_plan_count += 1
            plans.append(
                {
                    "plan": plan,
                    "risk": (
                        (assessment or {}).get("risk", {}).get("overall_risk")
                        if assessment
                        else None
                    ),
                }
            )

        # Recent investigations: the enterprise scope plus every network.
        enterprise_dir = enterprise_scope_dir(output_dir())
        investigation_sets = [
            shape_investigations(
                load_investigation_history(enterprise_dir),
                scope_id=GLOBAL_SCOPE_ID,
                network=GLOBAL_SCOPE_LABEL,
            )
        ]
        prediction_rows = [
            shape_prediction(
                load_json(enterprise_dir / "prediction_report.json"),
                scope_id=GLOBAL_SCOPE_ID,
                network=GLOBAL_SCOPE_LABEL,
            )
        ]
        change_rows = []
        failures = []
        for scope in aggregated:
            investigation_sets.append(
                shape_investigations(
                    load_investigation_history(scope.output_dir),
                    scope_id=scope.scope_id,
                    network=scope.label,
                )
            )
            prediction_rows.append(
                shape_prediction(
                    load_json(scope.output_dir / "prediction_report.json"),
                    scope_id=scope.scope_id,
                    network=scope.label,
                )
            )
            report = load_json(scope.output_dir / "state_change_report.json")
            if isinstance(report, dict) and (
                report.get("change_count") or report.get("active_issue_count")
            ):
                change_rows.append(
                    {
                        "network": scope.label,
                        "scope_id": scope.scope_id,
                        "change_count": report.get("change_count") or 0,
                        "active_issue_count": report.get("active_issue_count")
                        or 0,
                        "generated_at": report.get("generated_at"),
                    }
                )
            record = HistoryRepository(scope.history_root).latest()
            if record is not None and record.failures:
                # PR-043.10 (POLISH, Part 1): unused CIDR addresses must never
                # generate a Mission recommendation. Count only genuine
                # discovery-coverage failures — reachable devices that could
                # not be authenticated — from the graph's discovery
                # statistics; a CIDR scan's empty addresses are excluded.
                snapshot = load_json(scope.snapshot_path)
                stats = (
                    (snapshot or {}).get("metadata", {}).get("discovery_statistics")
                )
                if isinstance(stats, dict):
                    coverage_failures = int(stats.get("authentication_failures") or 0)
                else:
                    coverage_failures = len(record.failures)  # legacy snapshots
                if coverage_failures:
                    failures.append(
                        {
                            "network": scope.label,
                            "scope_id": scope.scope_id,
                            "run_id": record.record_id,
                            "count": coverage_failures,
                        }
                    )
        investigations = merge_recent(investigation_sets)
        predictions = [row for row in prediction_rows if row]
        predictions.sort(
            key=lambda row: str(row.get("generated_at") or ""), reverse=True
        )
        recommendations = build_recommendations(
            contributions=[c.to_dict() for c in graph.contributions],
            draft_plan_count=draft_plan_count,
            discovery_failures=failures,
            predictions=predictions,
            active_issues=[
                {
                    "network": row["network"],
                    "scope_id": row["scope_id"],
                    "count": row["active_issue_count"],
                }
                for row in change_rows
                if row["active_issue_count"]
            ],
            has_any_data=bool(aggregated),
            now=now,
        )
        freshness_ages = {
            contribution.profile_id: describe_age(contribution.observed_at, now)
            for contribution in graph.contributions
        }
        activity = build_activity_stream(
            discoveries=recent[:6],
            investigations=investigations,
            predictions=predictions,
            plans=plans,
            changes=change_rows,
        )
        return render_template(
            "mission.html",
            summary=summary,
            recent=recent[:6],
            plans=plans,
            investigations=investigations,
            predictions=predictions[:4],
            change_rows=change_rows,
            recommendations=recommendations,
            freshness_ages=freshness_ages,
            activity=activity,
            **(enterprise_context(graph) if graph.devices else {}),
            **context,
        )

    # -- Profiles -----------------------------------------------------------

    @app.route("/profiles")
    def profiles():
        # Management lists every observation point, archived included, and
        # surfaces evidence-based duplicate-network candidates (PR-043.9).
        rows = [
            profile_row(p)
            for p in profile_service().list_profiles(include_archived=True)
        ]
        resolution = network_resolution()
        return render_template(
            "profiles.html",
            profiles=rows,
            networks=[network.to_dict() for network in resolution.networks],
            duplicate_candidates=[
                candidate.to_dict()
                for candidate in resolution.duplicate_candidates
            ],
            **base_context("profiles"),
        )

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
            flash(
                "Discovery profile deleted. The network's enterprise "
                "knowledge is unaffected if another profile observes it.",
                "success",
            )
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
        return redirect(url_for("profiles"))

    @app.route("/profiles/<name>/duplicate", methods=["POST"])
    def profile_duplicate(name: str):
        try:
            new_name = request.form.get("new_name", "").strip() or None
            clone = profile_service().duplicate_profile(name, new_name=new_name)
            flash(
                f"Profile duplicated as {clone.name!r}. It observes the same "
                "estate — Atlas will flag it as a duplicate-network "
                "candidate once it discovers.",
                "success",
            )
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
        return redirect(url_for("profiles"))

    @app.route("/profiles/<name>/archive", methods=["POST"])
    def profile_archive(name: str):
        restore = request.form.get("restore") == "1"
        try:
            profile_service().archive_profile(name, archived=not restore)
            flash(
                "Profile restored." if restore else
                "Profile archived — hidden from discovery and enterprise "
                "aggregation. Its network knowledge is retained.",
                "success",
            )
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

    # -- Discovery Wizard (PR-043.2: enterprise discovery modes) --------------

    def _wizard_plan_from_form(form):
        """Resolve the wizard form into a DiscoveryPlan, or (None, error)."""

        from founderos_atlas.discovery import DiscoveryPlanError, resolve_plan

        mode = form.get("mode", "seed").strip()
        policy = form.get("policy", "balanced").strip()
        exclusions = _csv(form.get("exclusions"))

        def limit(name, default):
            value = form.get(name, "").strip()
            return int(value) if value.isdigit() and int(value) > 0 else default

        try:
            plan = resolve_plan(
                mode,
                seed=form.get("seed", "").strip() or None,
                seeds=_csv(form.get("seeds")),
                cidr=form.get("cidr", "").strip() or None,
                csv_text=form.get("csv_text", "") or None,
                policy=policy,
                max_depth=limit("max_depth", 1),
                max_devices=limit("max_devices", 64),
                timeout_seconds=limit("timeout_seconds", 15),
                concurrency=limit("concurrency", 1),
                exclusions=exclusions,
                allow_large_scan=form.get("allow_large_scan") == "yes",
            )
        except DiscoveryPlanError as error:
            return None, str(error)
        return plan, None

    @app.route("/discovery/wizard")
    def discovery_wizard():
        return render_template(
            "discovery_wizard.html",
            credential_sets=credential_service().list_sets(),
            plan=None,
            error=None,
            **base_context("discovery"),
        )

    @app.route("/discovery/wizard/preview", methods=["POST"])
    def discovery_wizard_preview():
        plan, error = _wizard_plan_from_form(request.form)
        return render_template(
            "discovery_wizard.html",
            credential_sets=credential_service().list_sets(),
            plan=plan.to_dict() if plan else None,
            form=request.form,
            error=error,
            **base_context("discovery"),
        )

    @app.route("/discovery/wizard/start", methods=["POST"])
    def discovery_wizard_start():
        plan, error = _wizard_plan_from_form(request.form)
        if plan is None:
            flash(error, "error")
            return redirect(url_for("discovery_wizard"))
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        credential_sets = tuple(request.form.getlist("credential_sets"))
        # A profile needs a way in — its own credential, or a credential set.
        # Sets alone are sufficient: their entries carry their own usernames and
        # passwords. Demanding a username and password anyway made an operator
        # who had picked a saved set retype a credential Atlas never needed.
        if not name:
            flash("A profile name is required to run discovery.", "error")
            return redirect(url_for("discovery_wizard"))
        if not (username and password) and not credential_sets:
            flash(
                "Discovery needs a way to authenticate: a username and "
                "password, or a credential set.",
                "error",
            )
            return redirect(url_for("discovery_wizard"))
        seeds = plan.seed_addresses
        try:
            service = profile_service()
            if service.repository.exists(name):
                service.update_profile(
                    name,
                    management_ip=seeds[0],
                    username=username,
                    password=password,
                    seeds=seeds[1:],
                    # Remember the range that was typed, not just the
                    # addresses it expanded into (PR-047A).
                    seed_cidr=plan.attributes.get("cidr"),
                    max_depth=plan.effective_depth,
                    max_devices=plan.max_devices,
                    collect_configuration=plan.collect_configuration,
                    credential_sets=credential_sets,
                    description=f"{plan.mode} · {plan.policy} policy",
                )
            else:
                service.add_profile(
                    name=name,
                    management_ip=seeds[0],
                    username=username,
                    password=password,
                    seeds=seeds[1:],
                    seed_cidr=plan.attributes.get("cidr"),
                    max_depth=plan.effective_depth,
                    max_devices=plan.max_devices,
                    collect_configuration=plan.collect_configuration,
                    credential_sets=credential_sets,
                    description=f"{plan.mode} · {plan.policy} policy",
                )
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
            return redirect(url_for("discovery_wizard"))
        try:
            job, _ = job_manager().start(name)
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
            return redirect(url_for("discovery_wizard"))
        session["scope"] = job.profile_id
        flash(
            f"Discovery started for {name} — {len(seeds)} candidate "
            f"address(es), {plan.policy} policy.",
            "success",
        )
        return redirect(url_for("discovery"))

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
                        "Select a discovery profile. The Enterprise scope "
                        "is a federated view — discovery always runs from "
                        "one observation point."
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

    @app.route("/discovery/console")
    def discovery_console():
        """The live execution console (PR-043.3): worker pool, queue,
        per-stage metrics, and controls for a pooled discovery run."""

        context, _scopes, _scope_id = scoped_context("discovery")
        return render_template("discovery_console.html", **context)

    @app.route("/api/discovery/execution/demo")
    def api_discovery_execution_demo():
        """A representative execution snapshot so the console renders and
        is testable without a live long-running run. Deterministic; the
        same shape a real pooled run's ``execution.snapshot()`` returns.

        ``?state=running`` returns a mid-run sample (alive workers,
        draining queue, ETA); the default returns a completed run with a
        real reconciled node inventory, honest metrics, and the log.
        """

        if request.args.get("state") == "running":
            return jsonify(_running_execution_sample())
        return jsonify(_completed_execution_demo())

    # -- Configuration Memory (PR-044) -------------------------------------

    def display_timezone():
        """The zone the GUI renders stored UTC instants in (display only)."""

        from .timefmt import resolve_timezone

        return resolve_timezone(app.config.get("ATLAS_DISPLAY_TIMEZONE"))

    def config_memory_store(scope):
        """The Configuration Memory of one scope — what Atlas remembers."""

        from founderos_atlas.config_memory import ConfigMemoryStore

        return ConfigMemoryStore(scope.output_dir / "config-memory")

    def config_memory_scopes(scopes, scope_id):
        """The scopes a Configuration view covers: one network, or all."""

        if scope_id == GLOBAL_SCOPE_ID:
            return aggregation_scopes(scopes)
        return (scopes[scope_id],)

    # -- Enterprise Memory (PR-045) ----------------------------------------

    def memory_store(scope):
        from founderos_atlas.enterprise_memory import EnterpriseMemoryStore

        return EnterpriseMemoryStore(scope.output_dir / "enterprise-memory")

    def memory_service(scope):
        from founderos_atlas.enterprise_memory import EnterpriseMemory

        return EnterpriseMemory(memory_store(scope))

    def memory_scopes(scopes, scope_id):
        if scope_id == GLOBAL_SCOPE_ID:
            return aggregation_scopes(scopes)
        return (scopes[scope_id],)

    def _find_memory(scopes, scope_id, *, session_id=None, device_id=None):
        """(service, scope) for the scope that holds a given session/device."""

        for scope in memory_scopes(scopes, scope_id):
            service = memory_service(scope)
            if session_id is not None and service.get_discovery_session(session_id):
                return service, scope
            if device_id is not None and service.get_device_memory(device_id):
                return service, scope
        return None, None

    # -- Evidence Explorer (PR-047B, PROOF) --------------------------------
    #
    # The page these routes replaced reported on the storage engine: unique
    # blobs, deduplicated observations, stored bytes. The drill-down beneath it
    # was good and complete, and nothing outside it ever pointed in, so an
    # operator asking "why does Atlas believe this?" landed on a wall of
    # counters. These routes answer the operator's four questions instead —
    # what was collected, from where, what failed, and what depends on it —
    # over exactly the same records. Enterprise Memory, CORTEX and the blob
    # store are untouched; every derivation lives in web/evidence_view.py.

    EVIDENCE_PAGE_SIZE = 50

    # A configuration can be tens of thousands of lines. Rendering all of it
    # into a <pre> is how a page stops responding, so the view is capped and
    # says so — the whole thing is always one Download click away, and the cap
    # is on *rendering*, never on what Atlas stored.
    EVIDENCE_MAX_VIEW_LINES = 2000

    def _page_arg(name: str = "page", default: int = 1) -> int:
        """A page number from the query string, or the default.

        A hand-edited "?page=banana" is an operator typo, not an error worth a
        500 — it means "the first page".
        """

        try:
            return int(request.args.get(name) or default)
        except (TypeError, ValueError):
            return default

    def _evidence_sessions(scopes, scope_id):
        rows: list[dict] = []
        for scope in memory_scopes(scopes, scope_id):
            for session in memory_store(scope).list_sessions():
                row = session.to_dict()
                row["scope_id"] = scope.scope_id
                rows.append(row)
        rows.sort(key=lambda s: s["started_at"], reverse=True)
        return rows

    def _evidence_storage_totals(scopes, scope_id):
        """The storage internals — kept, but demoted to System Details."""

        totals = {"sessions": 0, "devices": 0, "evidence_records": 0,
                  "configuration_snapshots": 0, "unique_blobs": 0,
                  "deduplicated": 0, "stored_bytes": 0}
        for scope in memory_scopes(scopes, scope_id):
            for key, value in memory_store(scope).statistics().items():
                if key in totals:
                    totals[key] += value
        return totals

    def _session_scope(scopes, scope_id, session_id):
        for scope in memory_scopes(scopes, scope_id):
            if memory_store(scope).get_session(session_id):
                return scope
        return None

    def _matches_filters(row, filters):
        """Server-side filtering (Part 7) — no new search engine, just the
        fields the operator can see, matched against what they typed."""

        if filters["device"] and row.get("device_id") != filters["device"]:
            return False
        if filters["platform"] and (row.get("platform") or "") != filters["platform"]:
            return False
        if filters["command"] and (row.get("command") or "") != filters["command"]:
            return False
        if filters["status"] and (row.get("collection_status") or "") != filters["status"]:
            return False
        if filters["source"] and (row.get("source") or "") != filters["source"]:
            return False
        if filters["q"]:
            needle = filters["q"].casefold()
            haystack = " ".join(str(row.get(key) or "") for key in (
                "hostname", "device_id", "command", "platform", "source",
                "software_version",
            )).casefold()
            if needle not in haystack:
                return False
        return True

    def _evidence_filters():
        return {
            "device": (request.args.get("device") or "").strip(),
            "platform": (request.args.get("platform") or "").strip(),
            "command": (request.args.get("command") or "").strip(),
            "status": (request.args.get("status") or "").strip(),
            "source": (request.args.get("source") or "").strip(),
            "q": (request.args.get("q") or "").strip(),
        }

    @app.route("/evidence")
    def evidence_page():
        """Evidence — what Atlas collected, from where, and whether it worked."""

        from .evidence_view import collection_summary, device_rows

        context, scopes, scope_id = scoped_context("memory")
        sessions = _evidence_sessions(scopes, scope_id)
        if not sessions:
            return render_template(
                "evidence_index.html", sessions=(), session=None, summary=None,
                devices=(), filters=_evidence_filters(), options={},
                totals=_evidence_storage_totals(scopes, scope_id), **context,
            )

        requested = (request.args.get("session") or "").strip()
        session = next(
            (s for s in sessions if s["session_id"] == requested), sessions[0]
        )
        scope = _session_scope(scopes, scope_id, session["session_id"])
        store = memory_store(scope)
        records = [
            r.to_dict()
            for r in store.evidence_records(discovery_session=session["session_id"])
        ]
        snapshots = [
            s.to_dict() for s in store.configuration_snapshots()
            if s.discovery_session == session["session_id"]
        ]

        # The summary describes the SESSION, not the filter. A filtered view
        # that also re-scored completeness would let an operator narrow to one
        # device and read its number as the network's.
        summary = collection_summary(session, records, snapshots).to_dict()

        filters = _evidence_filters()
        visible = [r for r in records if _matches_filters(r, filters)]
        # Snapshots must be filtered alongside the records they came from. A
        # configuration IS one of these records (the same bytes under another
        # view), so a snapshot surviving a filter that excluded every one of
        # its device's records would put the device back in the table and make
        # "no evidence matches these filters" unreachable.
        seen = {r.get("device_id") for r in visible}
        devices = device_rows(
            visible, [s for s in snapshots if s.get("device_id") in seen]
        )

        options = {
            "platforms": sorted({r.get("platform") for r in records if r.get("platform")}),
            "commands": sorted({r.get("command") for r in records if r.get("command")}),
            "statuses": sorted({
                r.get("collection_status") for r in records if r.get("collection_status")
            }),
            "sources": sorted({r.get("source") for r in records if r.get("source")}),
        }
        return render_template(
            "evidence_index.html",
            sessions=sessions, session=session, summary=summary,
            devices=devices, filters=filters, options=options,
            filtered=any(filters.values()),
            record_count=len(records), visible_count=len(visible),
            totals=_evidence_storage_totals(scopes, scope_id),
            **context,
        )

    @app.route("/evidence/device/<path:device_id>")
    def evidence_device_page(device_id: str):
        """One device's collected commands — provenance only, never output.

        No blob is read here (Part 11): the listing is built entirely from the
        records index, so opening a device with a 40MB configuration in its
        history costs the same as opening one without.
        """

        from .evidence_view import command_row, device_rows

        context, scopes, scope_id = scoped_context("memory")
        service, _scope = _find_memory(scopes, scope_id, device_id=device_id)
        if service is None:
            flash("Atlas has no memory of that device in this scope.", "error")
            return redirect(url_for("evidence_page"))

        memory = service.get_device_memory(device_id)
        session_id = (request.args.get("session") or "").strip()
        records = [r.to_dict() for r in service.get_raw_evidence(device_id)]
        if session_id:
            records = [r for r in records if r.get("discovery_session") == session_id]

        filters = _evidence_filters()
        visible = [r for r in records if _matches_filters(r, filters)]
        visible.sort(key=lambda r: (r.get("collected_at") or "", r.get("command") or ""),
                     reverse=True)

        page = max(1, _page_arg())
        total_pages = max(1, -(-len(visible) // EVIDENCE_PAGE_SIZE))
        page = min(page, total_pages)
        start = (page - 1) * EVIDENCE_PAGE_SIZE
        rows = [command_row(r) for r in visible[start:start + EVIDENCE_PAGE_SIZE]]

        snapshots = [s.to_dict() for s in service.get_configuration_history(device_id)]
        device = next(
            iter(device_rows(records, snapshots)),
            {"device_id": device_id, "hostname": memory.hostname if memory else device_id},
        )
        return render_template(
            "evidence_device.html",
            device=device, memory=memory.to_dict() if memory else None,
            rows=rows, filters=filters, session_id=session_id,
            sessions=_evidence_sessions(scopes, scope_id),
            page=page, total_pages=total_pages,
            visible_count=len(visible), record_count=len(records),
            configurations=snapshots,
            **context,
        )

    @app.route("/evidence/device/<path:device_id>/record/<sha>")
    def evidence_record_page(device_id: str, sha: str):
        """One command's evidence: masked output, the facts Atlas already has,
        and the conclusions that rest on it.

        This is the page every "why does Atlas believe this?" should end at.
        """

        from .evidence_view import command_row, normalized_facts

        context, scopes, scope_id = scoped_context("memory")
        service, scope = _find_memory(scopes, scope_id, device_id=device_id)
        if service is None:
            abort(404)
        record = next(
            (r for r in service.get_raw_evidence(device_id) if r.content_sha256 == sha),
            None,
        )
        if record is None:
            abort(404)

        view = service.view_evidence(record)
        text = view.text
        truncated = False
        total_lines = 0
        if text:
            lines = text.splitlines()
            total_lines = len(lines)
            if total_lines > EVIDENCE_MAX_VIEW_LINES:
                text = "\n".join(lines[:EVIDENCE_MAX_VIEW_LINES])
                truncated = True

        data = record.to_dict()
        snapshot = next(
            (s.to_dict() for s in service.get_configuration_history(device_id)
             if s.config_sha256 == record.content_sha256),
            None,
        )
        return render_template(
            "evidence_record.html",
            device_id=device_id, row=command_row(data), record=data,
            text=text, masked_line_count=view.masked_line_count,
            truncated=truncated, total_lines=total_lines,
            shown_lines=EVIDENCE_MAX_VIEW_LINES,
            facts=normalized_facts(data, snapshot=snapshot),
            usage=_evidence_usage(service, scope, data).to_dict(),
            **context,
        )

    def _evidence_usage(service, scope, record):
        """Which conclusions used this evidence (Part 6).

        Policies are evaluated only for evidence Atlas can actually trace — the
        running configuration — and only for this one device. Evaluating the
        whole pack across every device to render one page would make the page
        cost grow with the network.
        """

        from .evidence_view import UsedBy, is_traceable, used_by

        if not is_traceable(record):
            return used_by(record)
        try:
            from founderos_atlas.policy import PolicyEngine, default_pack

            engine = PolicyEngine()
            evaluations = [
                engine.evaluate_device(
                    service, record["device_id"], policy,
                    scope_label=getattr(scope, "label", ""),
                ).to_dict()
                for policy in default_pack().policies
            ]
        except Exception:  # noqa: BLE001
            # Usage is context, never the point of the page. If policy
            # evaluation is unavailable the evidence must still render — and
            # say honestly that usage could not be determined, not claim none.
            return UsedBy(findings=(), tracked=False, message=(
                "Atlas could not determine which conclusions use this evidence."
            ))
        return used_by(record, policy_evaluations=evaluations)

    @app.route("/evidence/device/<path:device_id>/record/<sha>/download")
    def evidence_record_download(device_id: str, sha: str):
        """Download one command's exact bytes — raw, for the local operator.

        Raw and unmasked: an export is the one place the raw text is the
        point, served only over the loopback GUI (as configuration export
        already is)."""

        from flask import Response

        _context, scopes, scope_id = scoped_context("memory")
        service, _scope = _find_memory(scopes, scope_id, device_id=device_id)
        if service is None:
            abort(404)
        text = service.download_evidence(sha)
        if text is None:
            abort(404)
        record = next(
            (r for r in service.get_raw_evidence(device_id) if r.content_sha256 == sha),
            None,
        )
        from .evidence_bundle import safe_name

        name = safe_name(record.command if record else "evidence",
                         fallback="evidence")
        _audit_raw_export(kind="command", subject=f"{device_id}:{sha[:10]}")
        return Response(
            text,
            content_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}-{sha[:10]}.txt"'},
        )

    @app.route("/evidence/device/<path:device_id>/bundle")
    def evidence_device_bundle(device_id: str):
        """This device's evidence as a zip — masked unless raw is asked for."""

        from flask import Response

        from .evidence_bundle import build_device_bundle, safe_name

        _context, scopes, scope_id = scoped_context("memory")
        service, _scope = _find_memory(scopes, scope_id, device_id=device_id)
        if service is None:
            abort(404)
        raw = request.args.get("raw") == "1"
        session_id = (request.args.get("session") or "").strip() or None
        data = build_device_bundle(service, device_id, raw=raw, session_id=session_id)
        if data is None:
            abort(404)
        if raw:
            _audit_raw_export(kind="device-bundle", subject=device_id)
        stem = safe_name(device_id, fallback="device")
        suffix = "-raw" if raw else ""
        return Response(
            data,
            content_type="application/zip",
            headers={
                "Content-Disposition":
                    f'attachment; filename="evidence-device-{stem}{suffix}.zip"'
            },
        )

    @app.route("/evidence/session/<path:session_id>/bundle")
    def evidence_session_bundle(session_id: str):
        """A whole discovery session's evidence as a zip, one folder per device."""

        from flask import Response

        from .evidence_bundle import build_session_bundle, safe_name

        _context, scopes, scope_id = scoped_context("memory")
        service, _scope = _find_memory(scopes, scope_id, session_id=session_id)
        if service is None:
            abort(404)
        raw = request.args.get("raw") == "1"
        data = build_session_bundle(service, session_id, raw=raw)
        if data is None:
            abort(404)
        if raw:
            _audit_raw_export(kind="session-bundle", subject=session_id)
        stem = safe_name(session_id, fallback="session")
        suffix = "-raw" if raw else ""
        return Response(
            data,
            content_type="application/zip",
            headers={
                "Content-Disposition":
                    f'attachment; filename="evidence-session-{stem}{suffix}.zip"'
            },
        )

    def _audit_raw_export(*, kind: str, subject: str) -> None:
        """Record that unmasked evidence left Atlas.

        A raw export is the one action here that can put a secret in a file the
        operator then forwards. It is allowed — the local operator owns these
        devices — but it is never silent.
        """

        app.logger.info("atlas.evidence.raw_export kind=%s subject=%s", kind, subject)

    # -- compatibility: /memory is where Evidence used to live --------------
    #
    # Renaming a route is not worth breaking a bookmark, a saved link, or the
    # two pages that already point here. Every old path resolves to its new
    # equivalent (PR-047A made the same promise for /management).

    @app.route("/memory")
    def memory_page():
        return redirect(url_for("evidence_page", **request.args.to_dict()), code=302)

    @app.route("/memory/session/<path:session_id>")
    def memory_session_page(session_id: str):
        return redirect(url_for("evidence_page", session=session_id), code=302)

    @app.route("/memory/device/<path:device_id>")
    def memory_device_page(device_id: str):
        return redirect(url_for("evidence_device_page", device_id=device_id), code=302)

    @app.route("/memory/device/<path:device_id>/evidence/<sha>")
    def memory_evidence_view(device_id: str, sha: str):
        return redirect(
            url_for("evidence_record_page", device_id=device_id, sha=sha), code=302
        )

    @app.route("/memory/device/<path:device_id>/evidence/<sha>/download")
    def memory_evidence_download(device_id: str, sha: str):
        return redirect(
            url_for("evidence_record_download", device_id=device_id, sha=sha), code=302
        )

    @app.route("/evidence/device/<path:device_id>/config/<sha>/download")
    def evidence_config_download(device_id: str, sha: str):
        """Download one configuration snapshot — raw, for the local operator."""

        from flask import Response

        _context, scopes, scope_id = scoped_context("memory")
        service, _scope = _find_memory(scopes, scope_id, device_id=device_id)
        if service is None:
            abort(404)
        text = service.download_configuration(sha)
        if text is None:
            abort(404)
        _audit_raw_export(kind="configuration", subject=f"{device_id}:{sha[:10]}")
        return Response(
            text,
            content_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="config-{sha[:10]}.txt"'},
        )

    @app.route("/memory/device/<path:device_id>/config/<sha>/download")
    def memory_config_download(device_id: str, sha: str):
        return redirect(
            url_for("evidence_config_download", device_id=device_id, sha=sha), code=302
        )

    # -- Enterprise Policy (PR-047, SENTINEL) ------------------------------

    @app.route("/policy")
    def policy_page():
        """Enterprise Policy — evaluate the installed policy pack against every
        device Atlas remembers, entirely through the CORTEX reasoning engine.

        Compliance is one policy pack; the engine is the reusable reasoning
        framework (PR-046). Every verdict is evidence-based, confidence-scored,
        and explained — a device with no configuration in memory is reported
        Unknown, never guessed."""

        from founderos_atlas.policy import PolicyEngine, list_packs

        from .timefmt import format_timestamp

        context, scopes, scope_id = scoped_context("policy")
        engine = PolicyEngine()
        memories = [
            (scope.label, memory_service(scope))
            for scope in memory_scopes(scopes, scope_id)
        ]
        report = engine.evaluate_scopes(
            memories, scope_label=context["active_scope_label"]
        )
        return render_template(
            "policy.html",
            report=report.to_dict(),
            packs=[p.to_dict() for p in list_packs()],
            generated_at=format_timestamp(report.generated_at, tz=display_timezone()),
            **context,
        )

    # -- Timeline (PR-047A FOCUS) ------------------------------------------

    @app.route("/timeline")
    def timeline_page():
        """Timeline — one front door for "what changed?".

        Changes, Configuration, Discoveries and Evidence each answered a slice
        of the same question from its own page. This is the workflow they belong
        to: one chronology across configuration changes and discovery runs, with
        each detailed view one click away. Nothing was removed — this is the
        entry point those four views were always missing.
        """

        from founderos_atlas.config_memory import enterprise_timeline

        from .timefmt import format_with_relative

        tz = display_timezone()
        context, scopes, scope_id = scoped_context("timeline")

        config_events: list = []
        totals = {
            "devices": 0, "versions": 0, "unique_configurations": 0,
            "deduplicated_observations": 0,
        }
        for scope in config_memory_scopes(scopes, scope_id):
            store = config_memory_store(scope)
            histories = store.histories()
            config_events.extend(
                enterprise_timeline(histories, config_text=store.config_text)
            )
            for key, value in store.statistics().items():
                if key in totals:
                    totals[key] += value

        discovery_rows: list[dict] = []
        for scope in aggregation_scopes(scopes) if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],):
            index = HistoryRepository(scope.history_root).load()
            discovery_rows.extend(history_rows(index, scope_label=scope.label))

        evidence_totals = {"sessions": 0, "evidence_records": 0}
        for scope in memory_scopes(scopes, scope_id):
            for key, value in memory_store(scope).statistics().items():
                if key in evidence_totals:
                    evidence_totals[key] += value

        activity = timeline_activity(config_events, discovery_rows)
        for entry in activity:
            entry["occurred_at"] = format_with_relative(entry["occurred_at"], tz=tz)

        return render_template(
            "timeline.html",
            activity=activity,
            change_count=len(config_events),
            discovery_count=len(discovery_rows),
            totals=totals,
            evidence_totals=evidence_totals,
            **context,
        )

    @app.route("/configuration")
    def configuration_page():
        """Browse remembered configuration: devices, versions, timeline."""

        from founderos_atlas.config_memory import enterprise_timeline, group_by_day

        from .timefmt import day_key_for, format_timestamp, format_with_relative

        tz = display_timezone()
        context, scopes, scope_id = scoped_context("configuration")
        devices: list[dict] = []
        events: list = []
        totals = {
            "devices": 0, "versions": 0, "observations": 0,
            "unique_configurations": 0, "stored_bytes": 0,
            "deduplicated_observations": 0,
        }
        for scope in config_memory_scopes(scopes, scope_id):
            store = config_memory_store(scope)
            histories = store.histories()
            for history in histories:
                latest = history.latest
                devices.append(
                    {
                        "device_id": history.device_id,
                        "hostname": history.hostname,
                        "network": history.network,
                        "scope_id": scope.scope_id,
                        "version_count": history.version_count,
                        "observations": history.total_observations,
                        "last_seen": (
                            format_with_relative(latest.last_seen, tz=tz)
                            if latest
                            else "—"
                        ),
                        "platform": latest.snapshot.platform if latest else "—",
                    }
                )
            events.extend(
                enterprise_timeline(histories, config_text=store.config_text)
            )
            for key, value in store.statistics().items():
                if key in totals:
                    totals[key] += value
        devices.sort(key=lambda row: row["hostname"].casefold())
        events.sort(key=lambda item: item.occurred_at, reverse=True)
        # Sorting and day-keying use the stored UTC instants; only the
        # rendered strings are converted to the operator's zone.
        days = group_by_day(tuple(events[:60]), day_of=day_key_for(tz))
        for day in days:
            for event in day["events"]:
                event["occurred_at"] = format_timestamp(event["occurred_at"], tz=tz)
        return render_template(
            "configuration.html",
            devices=devices,
            timeline=days,
            change_count=len(events),
            totals=totals,
            search=request.args.get("q", "").strip(),
            **context,
        )

    def _find_history(scopes, scope_id, device_id):
        """(store, history, scope) for a device across the active scope(s)."""

        for scope in config_memory_scopes(scopes, scope_id):
            store = config_memory_store(scope)
            history = store.history(device_id)
            if history is not None:
                return store, history, scope
        return None, None, None

    @app.route("/configuration/<path:device_id>")
    def configuration_device(device_id: str):
        """One device's version history, with an optional comparison."""

        from founderos_atlas.config_memory import (
            config_view,
            device_timeline,
            extract_facts,
            semantic_diff,
            text_diff,
        )

        from .timefmt import format_timestamp, format_with_relative

        tz = display_timezone()
        context, scopes, scope_id = scoped_context("configuration")
        store, history, _scope = _find_history(scopes, scope_id, device_id)
        if history is None:
            flash(
                "Atlas has no remembered configuration for that device in "
                "this scope.",
                "error",
            )
            return redirect(url_for("configuration_page"))

        latest = history.latest
        # Default comparison: the previous version against the latest.
        current_number = _int(request.args.get("current"), latest.version)
        default_previous = max(1, current_number - 1)
        previous_number = _int(request.args.get("previous"), default_previous)
        current = history.version(current_number) or latest
        previous = history.version(previous_number)

        comparison = None
        semantic = ()
        facts = None
        viewer = None
        current_text = store.config_text(current.config_sha256)
        if current_text is not None:
            # view() keeps the counts AND the detail behind them; an
            # operator opening a device asks "which neighbours", not "how
            # many".
            facts = extract_facts(current_text).view()
            # Reading a remembered configuration is the point of
            # remembering it. Masked — export is the only raw path.
            viewer = config_view(current_text).to_dict()
        if previous is not None and previous.version != current.version:
            before = store.config_text(previous.config_sha256)
            after = current_text
            if before is not None and after is not None:
                comparison = text_diff(before, after, context_lines=3).to_dict()
                semantic = tuple(
                    event.to_dict()
                    for event in semantic_diff(
                        extract_facts(before), extract_facts(after)
                    )
                )
        def _version_row(version):
            row = version.to_dict()
            row["first_seen"] = format_timestamp(version.first_seen, tz=tz)
            row["last_seen"] = format_with_relative(version.last_seen, tz=tz)
            return row

        def _timeline_row(event):
            row = event.to_dict()
            row["occurred_at"] = format_timestamp(event.occurred_at, tz=tz)
            return row

        return render_template(
            "configuration_device.html",
            history=history.to_dict(),
            versions=[_version_row(version) for version in history.versions],
            current=current.to_dict(),
            previous=previous.to_dict() if previous else None,
            comparison=comparison,
            semantic=semantic,
            facts=facts,
            viewer=viewer,
            timeline=[
                _timeline_row(event)
                for event in device_timeline(history, config_text=store.config_text)
            ],
            **context,
        )

    @app.route("/configuration/<path:device_id>/export/<int:version>")
    def configuration_export(device_id: str, version: int):
        """Export one remembered version as text.

        SENSITIVE: this is the exact device configuration. It is served
        only to the local operator over the loopback GUI, never masked —
        an export is the one place the raw text is the point.
        """

        from flask import Response

        from founderos_atlas.config import safe_artifact_name

        _context, scopes, scope_id = scoped_context("configuration")
        store, history, _scope = _find_history(scopes, scope_id, device_id)
        if history is None:
            abort(404)
        text = store.version_text(device_id, version)
        if text is None:
            abort(404)
        filename = f"{safe_artifact_name(history.hostname)}-v{version}.txt"
        return Response(
            text,
            # mimetype= appends its own charset; passing one here produced
            # "text/plain; charset=utf-8; charset=utf-8".
            content_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
                # Enterprise federation (PR-037A): one canonical graph with
                # provenance, merge decisions, and visible boundaries.
                graph, snapshot = enterprise_world()
                rows = get_enterprise_inventory(graph)
                site_options = sorted({row["site"] for row in rows})
                site_filter = request.args.get("site", "").strip()
                if site_filter:
                    rows = [row for row in rows if row["site"] == site_filter]
                visible_ids = {row["enterprise_id"] for row in rows}
                merge_rows = [
                    decision.to_dict()
                    for decision in graph.merge_decisions
                    if decision.merged and decision.enterprise_id in visible_ids
                ]
                return render_template(
                    "topology.html",
                    global_view=True,
                    enterprise=True,
                    inventory=rows,
                    merge_decisions=merge_rows,
                    site_options=site_options,
                    site_filter=site_filter,
                    viewers=viewers,
                    has_topology=snapshot is not None,
                    topology_src=(
                        f"/artifacts/{ENTERPRISE_ARTIFACT_PREFIX}atlas_topology.html"
                    ),
                    **enterprise_context(graph),
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

    # -- Prediction (PR-036B: what happens if I make this change?) -----------

    def validated_change_target(
        snapshot: dict, device: str, interface: str, label: str
    ):
        """Server-side validation of a (device, interface) pair against a
        snapshot — canonical values out, or an error message. Client-side
        selection is a convenience, never the authority."""

        from founderos_atlas.prediction import resolve_interface

        device_entry = next(
            (
                entry
                for entry in (snapshot or {}).get("devices") or ()
                if isinstance(entry, dict)
                and str(entry.get("hostname") or "").casefold() == device.casefold()
            ),
            None,
        )
        if device_entry is None:
            return None, None, (
                f"{device} is not in {label}'s latest discovery. "
                "Run discovery first."
            )
        device = str(device_entry.get("hostname"))  # canonical casing
        inventory = tuple(
            str(item.get("name"))
            for item in device_entry.get("interfaces") or ()
            if isinstance(item, dict) and item.get("name")
        )
        if not inventory:
            return None, None, (
                "No discovered interfaces are available. Run discovery first."
            )
        canonical, problem = resolve_interface(interface, inventory)
        if canonical is None:
            return None, None, f"Interface not accepted for {device}: {problem}."
        return device, canonical, None

    @app.route("/predict")
    def predict_page():
        context, scopes, scope_id = scoped_context("predict")
        if scope_id == GLOBAL_SCOPE_ID:
            # Enterprise prediction (PR-037A): the federated snapshot spans
            # every contributing profile; blast radii may cross sites.
            graph, snapshot = enterprise_world()
            enterprise_dir = enterprise_scope_dir(output_dir())
            return render_template(
                "predict.html",
                needs_scope=False,
                enterprise=True,
                devices=prediction_targets(snapshot),
                prediction=load_json(enterprise_dir / "prediction_report.json"),
                artifact_prefix=ENTERPRISE_ARTIFACT_PREFIX,
                **enterprise_context(graph),
                **context,
            )
        scope = scopes[scope_id]
        # Always the LATEST successful snapshot of the selected scope.
        snapshot = load_json(scope.snapshot_path)
        devices = prediction_targets(snapshot)
        prediction = load_json(scope.output_dir / "prediction_report.json")
        return render_template(
            "predict.html",
            needs_scope=False,
            enterprise=False,
            devices=devices,
            prediction=prediction,
            artifact_prefix=artifact_prefix(scope),
            **context,
        )

    @app.route("/predict/run", methods=["POST"])
    def predict_run():
        from founderos_atlas.prediction import (
            ChangeRequest,
            predict_change,
            render_prediction_json,
            render_prediction_markdown,
        )
        from founderos_atlas.sites import SiteCatalogRepository

        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        device = request.form.get("device", "").strip()
        interface = request.form.get("interface", "").strip()
        if not device or not interface:
            flash("A device and an interface are required.", "error")
            return redirect(url_for("predict_page"))
        evidence_overrides: dict = {}
        if scope_id == GLOBAL_SCOPE_ID:
            # Enterprise prediction (PR-037A): evidence comes from every
            # contributing profile scope, never guessed.
            graph, snapshot = enterprise_world()
            if snapshot is None:
                flash("No discovery has run yet in any network.", "error")
                return redirect(url_for("predict_page"))
            profiles = profile_service().list_profiles()
            out_dir = enterprise_scope_dir(output_dir())
            history_root = out_dir / "history"
            seed_addresses = enterprise_seed_addresses(profiles)
            evidence_overrides = {
                "fresh": overall_freshness(graph.contributions),
                "history_available": bool(graph.contributions),
                "configuration_captured": device.casefold()
                in {
                    name.casefold()
                    for name in enterprise_captured_configs(
                        output_dir(), profiles, graph
                    )
                },
            }
            scope_label = GLOBAL_SCOPE_LABEL
        else:
            scope = scopes[scope_id]
            snapshot = load_json(scope.snapshot_path) or {}
            out_dir = scope.output_dir
            history_root = scope.history_root
            # Profile seed addresses are proven management entry points;
            # they feed the management-plane reachability evaluation.
            seed_addresses = ()
            for profile in profile_service().list_profiles():
                if profile.profile_id == scope.scope_id:
                    seed_addresses = profile.all_seeds
                    break
            scope_label = scope.label
        device, interface, problem = validated_change_target(
            snapshot, device, interface, scope_label
        )
        if problem is not None:
            flash(problem, "error")
            return redirect(url_for("predict_page"))
        generated_at = now_iso()
        change = ChangeRequest(
            request_id=f"gui-{device}-{interface}".replace(" ", "-"),
            change_type="shutdown-interface",
            target_device=device,
            target_object=interface,
            requested_at=generated_at,
            profile_id=scope_id,
            reason=(request.form.get("reason", "").strip() or None),
            maintenance_window=(
                request.form.get("maintenance_window", "").strip() or None
            ),
            requester=(request.form.get("requester", "").strip() or None),
        )
        prediction = predict_change(
            change,
            output_dir=out_dir,
            history_root=history_root,
            generated_at=generated_at,
            site_catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
            seed_addresses=seed_addresses,
            **evidence_overrides,
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prediction_report.json").write_text(
            render_prediction_json(prediction), encoding="utf-8"
        )
        (out_dir / "prediction_report.md").write_text(
            render_prediction_markdown(prediction), encoding="utf-8"
        )
        flash("Prediction generated.", "success")
        return redirect(url_for("predict_page"))

    # -- Path Intelligence (PR-037: where does communication stop, and why?) --

    @app.route("/paths")
    def paths_page():
        from founderos_atlas.path_intelligence import load_investigation_history

        context, scopes, scope_id = scoped_context("paths")
        if scope_id == GLOBAL_SCOPE_ID:
            # Enterprise path intelligence (PR-037A): FLOW investigates
            # across the federated canonical topology.
            graph, snapshot = enterprise_world()
            enterprise_dir = enterprise_scope_dir(output_dir())
            return render_template(
                "paths.html",
                needs_scope=False,
                enterprise=True,
                devices=prediction_targets(snapshot),
                investigation=load_json(
                    enterprise_dir / "path_investigation_report.json"
                ),
                past_investigations=load_investigation_history(enterprise_dir)[:10],
                artifact_prefix=ENTERPRISE_ARTIFACT_PREFIX,
                **enterprise_context(graph),
                **context,
            )
        scope = scopes[scope_id]
        snapshot = load_json(scope.snapshot_path)
        devices = prediction_targets(snapshot)
        investigation = load_json(scope.output_dir / "path_investigation_report.json")
        past = load_investigation_history(scope.output_dir)
        return render_template(
            "paths.html",
            needs_scope=False,
            enterprise=False,
            devices=devices,
            investigation=investigation,
            past_investigations=past[:10],
            artifact_prefix=artifact_prefix(scope),
            **context,
        )

    @app.route("/paths/run", methods=["POST"])
    def paths_run():
        from founderos_atlas.path_intelligence import investigate_path_for_scope

        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        source = request.form.get("source", "").strip()
        destination = request.form.get("destination", "").strip()
        if not source or not destination:
            flash("A source and a destination device are required.", "error")
            return redirect(url_for("paths_page"))
        generated_at = now_iso()
        # The engine itself resolves and reports unknown devices with
        # evidence-based explanations — no pre-validation needed here.
        if scope_id == GLOBAL_SCOPE_ID:
            graph, snapshot = enterprise_world()
            if snapshot is None:
                flash("No discovery has run yet in any network.", "error")
                return redirect(url_for("paths_page"))
            profiles = profile_service().list_profiles()
            enterprise_dir = enterprise_scope_dir(output_dir())
            investigate_path_for_scope(
                source,
                destination,
                output_dir=enterprise_dir,
                history_root=enterprise_dir / "history",
                generated_at=generated_at,
                profile_id=GLOBAL_SCOPE_ID,
                fresh=overall_freshness(graph.contributions),
                failed_hosts=enterprise_failed_hosts(output_dir(), profiles),
                captured_config_devices=enterprise_captured_configs(
                    output_dir(), profiles, graph
                ),
            )
        else:
            scope = scopes[scope_id]
            investigate_path_for_scope(
                source,
                destination,
                output_dir=scope.output_dir,
                history_root=scope.history_root,
                generated_at=generated_at,
                profile_id=scope.scope_id,
            )
        flash("Path investigation complete.", "success")
        return redirect(url_for("paths_page"))

    # -- Compass (PR-039: deterministic change planning) -----------------------

    def compass_repository():
        from founderos_atlas.compass import PlanRepository

        return PlanRepository(output_dir())

    @app.route("/compass")
    def compass_page():
        from founderos_atlas.compass import CHANGE_TYPES

        context, _scopes, _scope_id = scoped_context("compass")
        repository = compass_repository()
        plans = []
        for plan in repository.list_plans():
            _, assessment = repository.get(plan.plan_id)
            plans.append(
                {
                    "plan": plan,
                    "risk": (assessment or {}).get("risk") if assessment else None,
                }
            )
        return render_template(
            "compass.html",
            plans=plans,
            change_types=CHANGE_TYPES,
            **context,
        )

    @app.route("/compass/new", methods=["POST"])
    def compass_new():
        from founderos_atlas.compass import create_plan

        title = request.form.get("title", "").strip()
        if not title:
            flash("A plan title is required.", "error")
            return redirect(url_for("compass_page"))
        plan = create_plan(
            compass_repository(),
            title=title,
            maintenance_window=request.form.get("maintenance_window", ""),
            engineer=request.form.get("engineer", ""),
            cab_reference=request.form.get("cab_reference", "") or None,
            created_at=now_iso(),
        )
        flash(f"Plan '{plan.title}' created.", "success")
        return redirect(url_for("compass_plan_page", plan_id=plan.plan_id))

    @app.route("/compass/<plan_id>")
    def compass_plan_page(plan_id: str):
        from founderos_atlas.compass import CHANGE_TYPES

        context, _scopes, _scope_id = scoped_context("compass")
        plan, assessment = compass_repository().get(plan_id)
        if plan is None:
            flash("That maintenance plan no longer exists.", "error")
            return redirect(url_for("compass_page"))
        graph, snapshot = enterprise_world()
        return render_template(
            "compass_plan.html",
            plan=plan,
            assessment=assessment,
            devices=prediction_targets(snapshot),
            change_types=CHANGE_TYPES,
            **enterprise_context(graph),
            **context,
        )

    @app.route("/compass/<plan_id>/changes", methods=["POST"])
    def compass_add_change(plan_id: str):
        from founderos_atlas.compass import (
            CHANGE_TYPES,
            PlannedChange,
            add_change,
        )
        from founderos_atlas.prediction import resolve_interface

        repository = compass_repository()
        plan, _ = repository.get(plan_id)
        if plan is None:
            flash("That maintenance plan no longer exists.", "error")
            return redirect(url_for("compass_page"))
        device = request.form.get("device", "").strip()
        change_type = request.form.get("change_type", "").strip()
        interface = request.form.get("interface", "").strip() or None
        if not device or change_type not in CHANGE_TYPES:
            flash("A device and a valid change type are required.", "error")
            return redirect(url_for("compass_plan_page", plan_id=plan_id))
        # Validate against the enterprise snapshot — Compass plans across
        # the whole enterprise; client-side selection is never trusted.
        _graph, snapshot = enterprise_world()
        entry = next(
            (
                item
                for item in (snapshot or {}).get("devices") or ()
                if isinstance(item, dict)
                and str(item.get("hostname") or "").casefold() == device.casefold()
            ),
            None,
        )
        if entry is None:
            flash(
                f"{device} is not in the enterprise's latest discovery "
                "evidence. Run discovery first.",
                "error",
            )
            return redirect(url_for("compass_plan_page", plan_id=plan_id))
        device = str(entry.get("hostname"))
        if interface:
            inventory = tuple(
                str(item.get("name"))
                for item in entry.get("interfaces") or ()
                if isinstance(item, dict) and item.get("name")
            )
            canonical, problem = resolve_interface(interface, inventory)
            if canonical is None:
                flash(
                    f"Interface not accepted for {device}: {problem}.", "error"
                )
                return redirect(url_for("compass_plan_page", plan_id=plan_id))
            interface = canonical
        duration = request.form.get("estimated_duration_minutes", "").strip()
        rollback = request.form.get("rollback_available", "").strip()
        taken = {change.change_id for change in plan.changes}
        number = 1
        while f"c{number}" in taken:
            number += 1
        change = PlannedChange(
            change_id=f"c{number}",
            device=device,
            interface=interface,
            change_type=change_type,
            reason=request.form.get("reason", "").strip(),
            estimated_duration_minutes=int(duration) if duration.isdigit() else None,
            rollback_available=(
                True if rollback == "yes" else False if rollback == "no" else None
            ),
            notes=request.form.get("notes", "").strip(),
        )
        add_change(repository, plan, change, updated_at=now_iso())
        flash(f"Added: {change.title}.", "success")
        return redirect(url_for("compass_plan_page", plan_id=plan_id))

    @app.route(
        "/compass/<plan_id>/changes/<change_id>/remove", methods=["POST"]
    )
    def compass_remove_change(plan_id: str, change_id: str):
        from founderos_atlas.compass import remove_change

        repository = compass_repository()
        plan, _ = repository.get(plan_id)
        if plan is None:
            flash("That maintenance plan no longer exists.", "error")
            return redirect(url_for("compass_page"))
        remove_change(repository, plan, change_id, updated_at=now_iso())
        flash("Change removed; re-analyse the plan.", "success")
        return redirect(url_for("compass_plan_page", plan_id=plan_id))

    @app.route("/compass/<plan_id>/analyse", methods=["POST"])
    def compass_analyse(plan_id: str):
        from founderos_atlas.compass import analyse_plan_for_workspace

        repository = compass_repository()
        plan, _ = repository.get(plan_id)
        if plan is None:
            flash("That maintenance plan no longer exists.", "error")
            return redirect(url_for("compass_page"))
        if not plan.changes:
            flash("Add at least one planned change first.", "error")
            return redirect(url_for("compass_plan_page", plan_id=plan_id))
        analyse_plan_for_workspace(
            repository,
            plan,
            base_output_dir=output_dir(),
            profiles=profile_service().list_profiles(),
            generated_at=now_iso(),
            catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
            credential_memory=CredentialSuccessMemory(cfg("ATLAS_WORKSPACE_ROOT")),
        )
        flash("Plan analysed.", "success")
        return redirect(url_for("compass_plan_page", plan_id=plan_id))

    # -- Atlas Advisor (PR-042: the conversational guide) ----------------------

    def advisor_repository():
        from founderos_atlas.advisor import ConversationRepository

        return ConversationRepository(output_dir())

    def advisor_ask(question: str):
        """Answer through the SAME graph the GUI shows for the SELECTED
        scope (PR-043.9, Part 1) — Advisor orchestrates, never re-derives.

        At a network scope Advisor consumes only that network's graph, so
        its answer agrees with the scoped Mission/Topology; at the
        Enterprise scope it consumes the federated graph."""

        from founderos_atlas.advisor import ask

        scope_id = active_scope_id(known_scopes())
        graph, snapshot, profiles = scoped_world(scope_id)
        return ask(
            question,
            base_output_dir=output_dir(),
            profiles=profiles,
            graph=graph,
            snapshot=snapshot,
            search_index=current_search_index(),
            generated_at=now_iso(),
            repository=advisor_repository(),
        )

    @app.route("/advisor")
    def advisor_page():
        context, _scopes, _scope_id = scoped_context("advisor")
        conversations = advisor_repository().list_conversations()
        latest = None
        selected = request.args.get("conversation", "").strip()
        if selected.isdigit() and int(selected) < len(conversations):
            latest = conversations[int(selected)].get("response")
        elif conversations:
            latest = conversations[0].get("response")
        return render_template(
            "advisor.html",
            conversations=conversations[:8],
            response=latest,
            **context,
        )

    @app.route("/advisor/ask", methods=["POST"])
    def advisor_ask_route():
        question = request.form.get("question", "").strip()
        if not question:
            flash("Ask a question first.", "error")
            return redirect(url_for("advisor_page"))
        advisor_ask(question)
        return redirect(url_for("advisor_page"))

    @app.route("/api/advisor/ask", methods=["POST"])
    def api_advisor_ask():
        payload = request.get_json(silent=True) or request.form
        question = str(payload.get("question") or "").strip()
        if not question:
            return jsonify(error="A question is required."), 400
        return jsonify(advisor_ask(question).to_dict())

    # -- Universal search (PR-038: the front door to Atlas) -------------------

    search_service = SearchService()

    def current_search_index():
        """The cached index; rebuilt automatically when evidence changes
        (discovery, federation, prediction, investigations, changes)."""

        return search_service.index_for(
            output_dir(),
            profile_service().list_profiles(),
            workspace_root=cfg("ATLAS_WORKSPACE_ROOT"),
            catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
            credential_sets=credential_service().list_sets(),
            credential_memory=CredentialSuccessMemory(cfg("ATLAS_WORKSPACE_ROOT")),
        )

    @app.route("/api/search")
    def api_search():
        query = request.args.get("q", "").strip()
        response = search_enterprise(current_search_index(), query)
        return jsonify(response.to_dict())

    @app.route("/devices/<path:enterprise_id>")
    def device_details(enterprise_id: str):
        context, _scopes, _scope_id = scoped_context("topology")
        graph, _snapshot = enterprise_world()
        device = graph.device_by_id(enterprise_id)
        if device is None:
            return (
                render_template(
                    "device.html",
                    found=False,
                    enterprise_id=enterprise_id,
                    **context,
                ),
                404,
            )
        decision = graph.decision_for(device.enterprise_id)
        interfaces = graph.interfaces.get(device.enterprise_id, ())
        neighbor_by_port = {}
        links = []
        for link in graph.links:
            if link.local_enterprise_id == device.enterprise_id:
                links.append(link)
                if link.local_interface:
                    neighbor_by_port[link.local_interface.casefold()] = (
                        link.remote_hostname
                    )
            elif link.remote_enterprise_id == device.enterprise_id:
                links.append(link)
                if link.remote_interface:
                    neighbor_by_port[link.remote_interface.casefold()] = (
                        link.local_hostname
                    )
        return render_template(
            "device.html",
            found=True,
            device=device,
            decision=decision,
            interfaces=interfaces,
            neighbor_by_port=neighbor_by_port,
            links=links,
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
        root_cause_data = load_json(scope.output_dir / "root_cause_report.json") or {}
        return render_template(
            "incidents.html",
            global_view=False,
            report=report,
            root_cause=root_cause_data.get("most_important"),
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
        incident_markdown = render_incident_report_markdown(report)
        # Investigations automatically include the root cause analysis.
        root_cause_data = load_json(out / "root_cause_report.json")
        if root_cause_data:
            from founderos_atlas.root_cause import root_cause_incident_section

            incident_markdown += root_cause_incident_section(root_cause_data)
        (out / "incident_report.md").write_text(incident_markdown, encoding="utf-8")
        flash("Incident investigation generated.", "success")
        return redirect(url_for("incidents"))

    # -- Settings -----------------------------------------------------------

    @app.route("/settings")
    def settings():
        from .timefmt import AUTO, timezone_label

        provider = resolve_credential_provider()
        try:
            available = provider.available()
        except Exception:  # pragma: no cover - defensive
            available = False
        tz_setting = str(app.config.get("ATLAS_DISPLAY_TIMEZONE") or AUTO)
        context = {
            "display_timezone_setting": tz_setting,
            "display_timezone_label": timezone_label(display_timezone()),
            "display_timezone_is_auto": tz_setting.casefold() == AUTO,
            "workspace_root": str(cfg("ATLAS_WORKSPACE_ROOT")),
            "output_dir": str(output_dir()),
            "history_root": str(cfg("ATLAS_HISTORY_ROOT")),
            "credential_provider": type(provider).__name__,
            "credential_available": available,
            "bind_host": cfg("ATLAS_HOST"),
            "atlas_version": "FounderOS v0.3 Alpha",
        }
        return render_template("settings.html", **context, **base_context("settings"))

    # -- Console (PR-044A) --------------------------------------------------

    def console_scopes(scopes, scope_id):
        """The scopes a console view covers: one network, or all of them."""

        if scope_id == GLOBAL_SCOPE_ID:
            return aggregation_scopes(scopes)
        return (scopes[scope_id],)

    def _scope_devices(scope):
        """Canonical devices in one scope, from its topology snapshot.

        A device is here only because Atlas opened an authenticated session
        to its management_ip and collected its identity. Unresolved peers
        are observations, not devices, and never appear.
        """

        import json

        path = scope.snapshot_path
        if not path.is_file():
            return ()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ()
        devices = data.get("devices")
        return tuple(devices) if isinstance(devices, list) else ()

    def _scope_login(scope):
        """(username, credential_ref, credential_name) for a scope."""

        profile = profile_for_scope(scope.scope_id)
        if profile is None:
            return None, None, None
        return profile.username, profile.credential_ref, profile.name

    def console_targets(scopes, scope_id):
        """Every canonical device in the active scope, resolved for SSH."""

        from founderos_atlas.console import resolve_targets

        found = []
        for scope in console_scopes(scopes, scope_id):
            username, credential_ref, credential_name = _scope_login(scope)
            found.extend(
                resolve_targets(
                    _scope_devices(scope),
                    network=scope.label,
                    scope_id=scope.scope_id,
                    username=username,
                    credential_ref=credential_ref,
                    credential_name=credential_name,
                )
            )
        return tuple(found)

    def console_target(scopes, scope_id, device_id: str):
        """One canonical device resolved for SSH, or None if there is no
        such canonical device in this scope (which is what an unresolved
        peer is)."""

        from founderos_atlas.console import find_target

        for scope in console_scopes(scopes, scope_id):
            username, credential_ref, credential_name = _scope_login(scope)
            target = find_target(
                _scope_devices(scope),
                device_id,
                network=scope.label,
                scope_id=scope.scope_id,
                username=username,
                credential_ref=credential_ref,
                credential_name=credential_name,
            )
            if target is not None:
                return target
        return None

    def console_credential_choices(scopes, scope_id):
        """Credential sets the operator may pick from, by reference.

        References only. The secrets they name stay in the credential store.
        """

        choices = []
        seen = set()
        for profile in profile_service().list_profiles(include_archived=True):
            if not profile.credential_ref or profile.credential_ref in seen:
                continue
            seen.add(profile.credential_ref)
            choices.append(
                {
                    "credential_ref": profile.credential_ref,
                    "name": profile.name,
                    "username": profile.username,
                }
            )
        return choices

    def console_credential_for(scopes, scope_id, credential_ref: str):
        """(username, password) for a credential reference.

        The one place the console reads a secret. It is handed straight to
        paramiko and never returned to a route, a template, or a socket.
        """

        for profile in profile_service().list_profiles(include_archived=True):
            if profile.credential_ref == credential_ref:
                password = profile_service().credential_provider.get(
                    credential_ref
                )
                return profile.username, password
        raise KeyError("unknown credential reference")

    def console_host_key_store():
        from founderos_atlas.console import HostKeyStore

        return HostKeyStore(Path(cfg("ATLAS_WORKSPACE_ROOT")) / "known_hosts.json")

    def console_audit():
        from founderos_atlas.console import ConsoleAuditLog

        return ConsoleAuditLog(output_dir() / ".atlas" / "console-audit.jsonl")

    def console_probe_host_key(host: str, port: int):
        from founderos_atlas.console import probe_host_key

        return probe_host_key(host, port, console_host_key_store())

    # -- Management / web access (PR-044B, PORTAL) -------------------------

    def management_store(scope):
        from founderos_atlas.management import ManagementServiceStore

        return ManagementServiceStore(scope.output_dir / "management-services.json")

    def _device_for(scopes, scope_id, device_id: str):
        """The raw canonical device record + owning scope, or (None, None)."""

        for scope in console_scopes(scopes, scope_id):
            for device in _scope_devices(scope):
                if str(device.get("device_id") or "").strip() == str(device_id).strip():
                    return device, scope
        return None, None

    def web_access_for(scopes, scope_id, device_id: str):
        """Resolve one canonical device's web-management actions."""

        from founderos_atlas.management import resolve_web_access

        device, scope = _device_for(scopes, scope_id, device_id)
        if device is None:
            return None
        services = management_store(scope).services_for(device_id)
        return resolve_web_access(
            device, network=scope.label, scope_id=scope.scope_id, services=services
        )

    def management_audit():
        # Web opens share the console's connection audit — one honest record
        # of who reached which device, how, and with what outcome.
        return console_audit()

    @app.route("/api/device/<path:device_id>/actions")
    def device_actions_api(device_id: str):
        """The universal device action, as JSON (PR-048A).

        The topology viewer is a generated artifact: it exists as a file on
        disk and cannot know at render time whether a device is SSH-eligible
        or has a verified web endpoint â€” both can change after any discovery
        or verification. When Atlas serves the artifact, the viewer asks here
        and gets the same answer every template gets: resolved from evidence,
        for the active scope, by console/resolve and management/resolve. One
        decision, one place, one more consumer.
        """

        _ctx, scopes, scope_id = scoped_context("topology")
        wanted = str(device_id).strip()
        hostname = (request.args.get("hostname") or "").strip().casefold()
        targets = console_targets(scopes, scope_id)
        target = next((t for t in targets if t.device_id == wanted), None)
        if target is None and hostname:
            # The enterprise topology mints its own node ids
            # ("ent:access1:172.20.20.23") that the console resolver has
            # never heard of. The hostname is the identity both graphs agree
            # on â€” the same fallback the template helpers already offer.
            target = next(
                (t for t in targets if t.hostname.casefold() == hostname), None
            )
        # Web access is keyed by canonical device id; follow the ssh
        # resolution to it when the caller's id was a federated one.
        canonical_id = target.device_id if target is not None else wanted
        web = web_access_for(scopes, scope_id, canonical_id)
        if target is None and web is None:
            # Not a canonical device in this scope â€” an unresolved peer, or a
            # stale id. No actions, said plainly.
            return jsonify(error="not a canonical device in this scope"), 404
        return jsonify(
            device_id=canonical_id,
            ssh=target.to_dict() if target is not None else None,
            web=web.to_dict() if web is not None else None,
        )

    # What the console surface needs from the GUI, without an import cycle.
    console_deps = SimpleNamespace(
        scoped_context=scoped_context,
        console_target=console_target,
        credential_choices=console_credential_choices,
        credential_for=console_credential_for,
        host_key_store=console_host_key_store,
        probe_host_key=console_probe_host_key,
        audit=console_audit,
        token_store=lambda: app.config["ATLAS_CONSOLE_TOKENS"],
        session_manager=lambda: app.config["ATLAS_CONSOLE_SESSIONS"],
    )

    @app.context_processor
    def _console_action_context():
        """Make the universal device action available to EVERY template.

        This is what stops eleven pages each growing their own idea of when
        SSH is allowed. A template asks for a target by device id or
        hostname; the answer always comes from console/resolve.py, from
        evidence, for the scope the operator is actually looking at.

        Resolution is cached per request: a topology page with 60 nodes
        reads the snapshot once, not sixty times.
        """

        def _targets_for_request():
            cache = getattr(g, "_console_targets", None)
            if cache is None:
                try:
                    _ctx, scopes, scope_id = scoped_context("topology")
                    cache = console_targets(scopes, scope_id)
                except Exception:  # noqa: BLE001 - a widget must not 500 a page
                    cache = ()
                g._console_targets = cache
            return cache

        def device_target(device_id=None, hostname=None):
            if not device_id and not hostname:
                return None
            cache = _targets_for_request()
            if device_id:
                wanted = str(device_id).strip()
                for target in cache:
                    if target.device_id == wanted:
                        return target.to_dict()
            if hostname:
                wanted = str(hostname).strip().casefold()
                for target in cache:
                    if target.hostname.casefold() == wanted:
                        return target.to_dict()
            # Not a canonical device in this scope — an unresolved peer, or a
            # name from another network. No target, therefore no SSH action.
            return None

        def devices_mentioned(*texts):
            """Canonical devices named in some text, resolved for SSH.

            Deterministic: an exact, word-boundary match of a canonical
            hostname against text Atlas itself produced. It cannot invent a
            device, and it cannot offer a session to something that is not a
            canonical device with a verified endpoint.

            This is how Advisor *suggests* a console. It never opens one —
            the engineer clicks, or nothing happens.
            """

            import re

            cache = _targets_for_request()
            haystack = " ".join(str(item or "") for item in texts)
            if not haystack.strip():
                return []
            found = []
            for target in cache:
                if not target.eligible:
                    continue
                pattern = r"\b" + re.escape(target.hostname) + r"\b"
                if re.search(pattern, haystack, re.IGNORECASE):
                    found.append(target.to_dict())
            return found

        def _web_access_for_request():
            cache = getattr(g, "_web_access", None)
            if cache is None:
                try:
                    _ctx, scopes, scope_id = scoped_context("topology")
                    cache = {}
                    for scope in console_scopes(scopes, scope_id):
                        store = management_store(scope)
                        for device in _scope_devices(scope):
                            did = str(device.get("device_id") or "").strip()
                            if not did:
                                continue
                            from founderos_atlas.management import resolve_web_access

                            cache[did] = resolve_web_access(
                                device,
                                network=scope.label,
                                scope_id=scope.scope_id,
                                services=store.services_for(did),
                            )
                except Exception:  # noqa: BLE001 - a widget must not 500 a page
                    cache = {}
                g._web_access = cache
            return cache

        def web_access(device_id=None, hostname=None):
            """Web-management actions for a device, for the action macro.

            Same rule as ``device_target``: resolved from evidence, for the
            active scope, cached per request. An unresolved peer or unknown
            name yields nothing.
            """

            cache = _web_access_for_request()
            if device_id:
                found = cache.get(str(device_id).strip())
                if found is not None:
                    return found.to_dict()
            if hostname:
                wanted = str(hostname).strip().casefold()
                for access in cache.values():
                    if access.hostname.casefold() == wanted:
                        return access.to_dict()
            return None

        # PR-047A: confidence presentation is a product decision, made once,
        # here — so no page invents its own idea of when a score is worth the
        # reader's attention. See web/confidence.py.
        from .confidence import confidence_detail, confidence_display

        return {
            "device_target": device_target,
            "devices_mentioned": devices_mentioned,
            "web_access": web_access,
            "confidence_display": confidence_display,
            "confidence_detail": confidence_detail,
        }

    @app.route("/console")
    def console_index():
        """Device Access — every way Atlas can reach a device, in one place.

        SSH and the web interface are two ways into the same device, resolved
        from the same evidence and the same verified management endpoint. They
        were two pages; a device is one thing, so this is one page. Verifying a
        web interface and defining an operator URL are actions *on a device*,
        and live here beside the actions they enable.
        """

        context, scopes, scope_id = scoped_context("console")
        targets = console_targets(scopes, scope_id)
        manager = app.config["ATLAS_CONSOLE_SESSIONS"]
        manager.expire_due()
        rows = [item.to_dict() for item in targets]
        # Web state per device, keyed by device id, so the table can show what
        # Atlas found without re-resolving per cell.
        web_by_device = {
            device_id: access
            for device_id, access in _web_access_map(scopes, scope_id).items()
        }
        return render_template(
            "console_index.html",
            targets=rows,
            web_by_device=web_by_device,
            eligible_count=sum(1 for item in targets if item.eligible),
            web_count=sum(1 for a in web_by_device.values() if a["any_web"]),
            https_count=sum(1 for a in web_by_device.values() if a["has_https"]),
            sessions=[item.to_dict() for item in manager.sessions()],
            operator=_console_operator().to_dict(),
            **context,
        )

    def _web_access_map(scopes, scope_id) -> dict:
        """Every device's resolved web-management state for the active scope."""

        from founderos_atlas.management import resolve_web_access

        found: dict = {}
        for scope in console_scopes(scopes, scope_id):
            store = management_store(scope)
            for device in _scope_devices(scope):
                device_id = str(device.get("device_id") or "").strip()
                if not device_id:
                    continue
                found[device_id] = resolve_web_access(
                    device,
                    network=scope.label,
                    scope_id=scope.scope_id,
                    services=store.services_for(device_id),
                ).to_dict()
        return found

    def _console_operator():
        from founderos_atlas.console import require_operator

        return require_operator()

    from .console_routes import register_console_routes

    register_console_routes(app, console_deps)

    # -- Management / web-access routes (PR-044B, PORTAL) ------------------

    def _guard_console_origin():
        """Same origin gate the console POSTs use (see console.security)."""

        from founderos_atlas.console import origin_allowed

        allowed = app.config.get("ATLAS_CONSOLE_ALLOWED_ORIGINS") or ()
        if not origin_allowed(
            request.headers.get("Origin"),
            host_header=request.headers.get("Host"),
            allowed_hosts=tuple(str(item) for item in allowed),
        ):
            return False
        return True

    @app.route("/management")
    def management_index():
        """Web management is not a place — it is one of the ways into a device.

        This page listed the same devices as Device Access, resolved from the
        same evidence, and offered the same actions. It is gone; the URL is not,
        so an existing link or bookmark still lands somewhere true. The verify /
        define / opened endpoints below remain — they are the write side of web
        access, and Device Access calls them.
        """

        return redirect(url_for("console_index"), code=302)

    @app.route("/management/<path:device_id>/verify", methods=["POST"])
    def management_verify(device_id: str):
        """Probe a device's management address for a web interface, now."""

        if not _guard_console_origin():
            return jsonify({"error": "This request did not come from Atlas."}), 403
        _context, scopes, scope_id = scoped_context("management")
        device, scope = _device_for(scopes, scope_id, device_id)
        if device is None:
            return jsonify({"error": "No such device in this scope."}), 404

        from founderos_atlas.console import resolve_target
        from founderos_atlas.management import (
            WebServiceVerifier,
            detect_certificate_change,
            resolve_web_access,
        )

        target = resolve_target(device, network=scope.label, scope_id=scope.scope_id)
        if not target.eligible or not target.management_ip:
            return jsonify({"error": target.reason, "state": target.state}), 409

        store = management_store(scope)
        known = store.known_index(device_id)
        verifier = WebServiceVerifier()
        try:
            services = verifier.verify(device_id, target.management_ip, known=known)
        except Exception:  # noqa: BLE001 - never leak a trace
            return jsonify(
                {"error": "Atlas could not complete web-service verification."}
            ), 502

        # Certificate-change detection against the previously stored HTTPS.
        cert_changed = False
        previous_fp = None
        for service in services:
            prev = known.get((service.protocol, service.port))
            changed, oldfp = detect_certificate_change(prev, service)
            if changed:
                cert_changed = True
                previous_fp = oldfp
        store.record_services(device_id, services)
        access = resolve_web_access(
            device, network=scope.label, scope_id=scope.scope_id,
            services=store.services_for(device_id),
            certificate_changed=cert_changed, previous_fingerprint=previous_fp,
        )
        management_audit().record(
            "web-service-verified", session_id="-",
            operator=_console_operator().name, device_id=device_id,
            hostname=target.hostname, management_ip=target.management_ip,
            port=0, credential_ref=None, result=access.state,
            detail=f"{len(services)} service(s)",
        )
        return jsonify(access.to_dict())

    @app.route("/management/<path:device_id>/define", methods=["POST"])
    def management_define(device_id: str):
        """Record an operator-stated management URL."""

        if not _guard_console_origin():
            return jsonify({"error": "This request did not come from Atlas."}), 403
        _context, scopes, scope_id = scoped_context("management")
        device, scope = _device_for(scopes, scope_id, device_id)
        if device is None:
            return jsonify({"error": "No such device in this scope."}), 404

        from urllib.parse import urlsplit

        from founderos_atlas.management import PROTOCOL_HTTP, PROTOCOL_HTTPS

        payload = request.json if request.is_json else {}
        url = str((payload or {}).get("url") or "").strip()
        reason = str((payload or {}).get("reason") or "").strip() or None
        parts = urlsplit(url)
        if parts.scheme not in (PROTOCOL_HTTPS, PROTOCOL_HTTP) or not parts.hostname:
            return jsonify(
                {"error": "Enter a full http(s):// management URL."}
            ), 400
        port = parts.port or (443 if parts.scheme == PROTOCOL_HTTPS else 80)
        service = management_store(scope).define_endpoint(
            device_id, url=url, protocol=parts.scheme, address=parts.hostname,
            port=port, user=_console_operator().name, reason=reason,
        )
        management_audit().record(
            "web-endpoint-defined", session_id="-",
            operator=_console_operator().name, device_id=device_id,
            hostname=str(device.get("hostname") or device_id),
            management_ip=parts.hostname, port=port, credential_ref=None,
            result="operator-defined", detail=url,
        )
        return jsonify(service.to_dict())

    @app.route("/management/<path:device_id>/opened", methods=["POST"])
    def management_opened(device_id: str):
        """Audit that the operator opened a device's web UI.

        The browser reports it after opening the tab. Records the URL and
        outcome — never a password, cookie, or anything the operator then
        typed into the device.
        """

        if not _guard_console_origin():
            return jsonify({"error": "This request did not come from Atlas."}), 403
        payload = request.json if request.is_json else {}
        url = str((payload or {}).get("url") or "").strip()
        protocol = str((payload or {}).get("protocol") or "").strip()
        _context, scopes, scope_id = scoped_context("management")
        device, _scope = _device_for(scopes, scope_id, device_id)
        hostname = str((device or {}).get("hostname") or device_id)
        management_audit().record(
            "web-management-opened", session_id="-",
            operator=_console_operator().name, device_id=device_id,
            hostname=hostname, management_ip="", port=0, credential_ref=None,
            result=("insecure-http" if protocol == "http" else "opened"),
            detail=url,
        )
        return jsonify({"recorded": True})

    # -- Artifact serving ---------------------------------------------------

    @app.route("/artifacts/<path:name>")
    def artifacts(name: str):
        return send_from_directory(str(output_dir()), name)


def _completed_execution_demo() -> dict:
    """A real completed pooled run over a representative subnet — honest
    nodes/metrics/log; the same schema a live run streams (PR-043.4)."""

    from founderos_atlas.discovery.executor import (
        DiscoveryExecution,
        OUTCOME_AUTH_FAILED,
        OUTCOME_DISCOVERED,
        OUTCOME_UNREACHABLE,
        run_pool,
    )

    class _Dev:
        def __init__(self, hostname, platform, vendor):
            self.hostname, self.platform, self.vendor = hostname, platform, vendor
            self.os_name = platform
            self.metadata = {}

    class _Res:
        def __init__(self, dev):
            self.device, self.interfaces = dev, ()

    addresses = [f"172.20.20.{i}" for i in range(11, 27)]
    clock = {"t": 0.0}

    def demo_clock():
        clock["t"] += 0.01
        return clock["t"]

    def worker(address, timer):
        last = int(address.rsplit(".", 1)[-1])
        with timer.stage("tcp_connect"):
            pass
        if last % 7 == 0:
            return None, OUTCOME_UNREACHABLE, None, f"{address} unreachable"
        if last % 5 == 0:
            return None, OUTCOME_AUTH_FAILED, None, f"{address} auth failed"
        with timer.stage("authentication"):
            pass
        with timer.stage("platform_detection"):
            pass
        platform = "FRRouting" if last % 3 == 0 else "IOSv"
        family = "frr" if last % 3 == 0 else "ios"
        dev = _Dev(f"r{last}", platform, family)
        return (
            _Res(dev),
            OUTCOME_DISCOVERED,
            family,
            f"{address} — {family} inventory complete",
        )

    execution = DiscoveryExecution(addresses, worker_count=8, clock=demo_clock)
    run_pool(execution, worker)
    return execution.snapshot()


def _running_execution_sample() -> dict:
    """A deterministic mid-run snapshot (alive workers, draining queue,
    ETA) matching the live snapshot schema — for the console's running
    state; explicitly a representative sample, not a live run."""

    from founderos_atlas.visualization.stencils import stencil_data_uri

    def node(last, family):
        role = "router" if family == "frr" else "layer2_switch" if last % 2 else "router"
        return {
            "address": f"172.20.20.{last}",
            "hostname": f"r{last}",
            "platform": "FRRouting" if family == "frr" else "IOSv",
            "vendor": family,
            "role": role,
            "role_evidence": "platform model evidence",
            "stencil": stencil_data_uri(role),
        }

    discovered = [node(i, "frr" if i % 3 == 0 else "ios") for i in range(11, 30)]
    return {
        "state": "running",
        "network": "Delhi Lab",
        "progress_percent": 42,
        "processed": 42,
        "total": 100,
        "eta_seconds": 48.0,
        "time_to_first_device_seconds": 2.1,
        "queue": {
            "total": 100,
            "completed_cached": 0,
            "pending": 50,
            "by_outcome": {
                "discovered": 38,
                "authentication-failed": 3,
                "unreachable": 1,
                "running": 8,
                "queued": 50,
            },
        },
        "queue_length": 50,
        "workers": [
            {"worker_id": 0, "address": "172.20.20.35", "stage": "collecting interfaces", "idle": False},
            {"worker_id": 1, "address": "172.20.20.41", "stage": "collecting routes", "idle": False},
            {"worker_id": 2, "address": "172.20.20.18", "stage": "platform detection", "idle": False},
            {"worker_id": 3, "address": "172.20.20.52", "stage": "ssh connected", "idle": False},
            {"worker_id": 4, "address": "172.20.20.61", "stage": "authenticating", "idle": False},
            {"worker_id": 5, "address": "172.20.20.29", "stage": "collecting neighbors", "idle": False},
            {"worker_id": 6, "address": "172.20.20.44", "stage": "connecting", "idle": False},
            {"worker_id": 7, "address": "172.20.20.12", "stage": "identity", "idle": False},
        ],
        "metrics": {
            "addresses_evaluated": 42,
            "ssh_reachable": 39,
            "authenticated": 38,
            "discovered": 38,
            "unsupported_platforms": 0,
            "authentication_failures": 3,
            "unreachable": 1,
            "skipped": 0,
            "elapsed_seconds": 151.0,
            "worker_count": 8,
            "average_discovery_seconds": 3.2,
            "average_ssh_seconds": 0.41,
            "average_authentication_seconds": 0.28,
            "average_platform_detection_seconds": 0.19,
            "slowest_stage": "configuration",
            "slowest_stage_seconds": 1.8,
            "devices_per_minute": 24.0,
            "worker_utilization_percent": 92,
        },
        "nodes": discovered,
        "log": [
            {"address": "172.20.20.35", "platform": "ios", "message": "172.20.20.35 — Cisco IOS inventory complete"},
            {"address": "172.20.20.41", "platform": "frr", "message": "172.20.20.41 — FRRouting routes collected"},
            {"address": "172.20.20.22", "platform": None, "message": "172.20.20.22 authentication failed"},
        ],
        "candidate_metrics": [],
    }


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


def _platform_label(family: str) -> str:
    """The name an operator recognises for a driver family.

    A snapshot records the driver's id (``frr``); every other Atlas surface
    shows its display name (``FRRouting``). The drivers already carry both, so
    the label comes from them rather than from a hand-kept lookup that would
    drift the first time a driver is added.
    """

    try:
        from founderos_atlas.platforms import default_registry

        for driver in default_registry().drivers():
            if driver.platform_id == family:
                return driver.display_name
    except Exception:  # noqa: BLE001 - a label must never break a page
        pass
    return family


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

        injected_factory = app.config["ATLAS_TRANSPORT_FACTORY"]
        base_factory = injected_factory or SSHDeviceTransport

        def tracking_factory(credentials):
            on_connect(credentials.host)
            return base_factory(credentials)

        # PR-043.6 (FALCON): gate real SSH behind a fast TCP reachability
        # probe so dead subnet addresses never pay an SSH timeout. Only
        # applied with the real transport — an injected (test/fake) factory
        # skips the probe so scripted networks are never TCP-probed.
        reachability = None
        if injected_factory is None:
            from founderos_atlas.transport.reachability import TcpReachability

            reachability = TcpReachability()

        out = app.config["ATLAS_OUTPUT_DIR"]
        atlas_discover_command(
            profile=profile_name,
            profile_service=app.config["ATLAS_PROFILE_SERVICE"],
            transport_factory=tracking_factory,
            reachability=reachability,
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
        # PR-043: the platform mix comes from the run's own snapshot.
        snapshot = load_json(scope.snapshot_path) or {}
        metadata = snapshot.get("metadata") or {}
        platforms = metadata.get("platforms") or {}
        # PR-043.1: honest relationship categories — physical links vs
        # routing adjacencies vs protocol peers vs unresolved peers.
        relations = metadata.get("relationships") or {}
        # The run's own statistics already separate the two things a
        # non-connecting address can mean, and have since PR-043.10. Reading
        # them here is what stops the GUI announcing "245 verified management
        # endpoint(s) could not be reached" about 245 addresses that simply
        # have no device on them — while this very snapshot recorded
        # discovery_completeness_percent: 100 and authentication_failures: 0.
        # Legacy snapshots carry no statistics; then both counts stay None and
        # the job says nothing rather than guessing.
        stats = metadata.get("discovery_statistics") or {}
        return {
            "devices": record.device_count,
            "relationships": record.relationship_count,
            "configurations_collected": record.configured_device_count,
            "duration_seconds": record.duration_seconds,
            "network_status": record.network_status,
            "failed_devices": len(record.failures),
            "auth_failed_devices": stats.get("authentication_failures"),
            "addresses_without_device": stats.get("unused_addresses"),
            "addresses_scanned": stats.get("addresses_scanned"),
            "discovery_completeness_percent": stats.get(
                "discovery_completeness_percent"
            ),
            "platforms": ", ".join(
                f"{_platform_label(name)}: {count}"
                for name, count in sorted(platforms.items())
            ),
            "physical_links": relations.get("physical_links"),
            "routing_adjacencies": relations.get("routing_adjacencies"),
            "protocol_peers": relations.get("protocol_peers"),
            "unresolved_peers": relations.get("unresolved_peers"),
        }

    return run
