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
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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
from founderos_atlas.web.linking import scoped_url
from founderos_atlas.web.redirects import safe_redirect_target
from founderos_atlas.identity import (
    PeerResolutionConflictError,
    PeerResolutionRepository,
    resolution_candidates,
)
from founderos_atlas.search import SearchService, search_enterprise
from founderos_atlas.sites import (
    SITE_TYPES,
    Site,
    SiteCatalog,
    SiteCatalogRepository,
    SiteOverrideConflictError,
    SiteOverrideRepository,
)
from founderos_atlas.topology import TopologySnapshot
from founderos_atlas.visualization import (
    TOPOLOGY_VISUAL_STYLE_VERSION,
    TopologyRenderer,
    topology_visual_style_is_current,
)
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
    AdministrationRepository,
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


def _viewer_has_current_visual_style(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            return topology_visual_style_is_current(handle.read(512))
    except (OSError, UnicodeError):
        return False


def _viewer_has_site_override_revision(
    path: Path, revision: int, identity_revision: int = 0
) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.read(1024)
    except (OSError, UnicodeError):
        return False
    return (
        f"<!-- ATLAS_SITE_OVERRIDE_REVISION={revision} -->" in header
        and (
            f"<!-- ATLAS_IDENTITY_RESOLUTION_REVISION={identity_revision} -->"
            in header
        )
    )


def _current_topology_viewer_url(
    path: str, artifact_path: Path | None = None
) -> str:
    """Cache-bust current HTML after style or persisted curation changes."""

    artifact_version = 0
    if artifact_path is not None:
        try:
            artifact_version = artifact_path.stat().st_mtime_ns
        except OSError:
            pass
    return (
        f"{path}?visual_style={TOPOLOGY_VISUAL_STYLE_VERSION}"
        f"&artifact_version={artifact_version}"
    )


def _configuration_viewer_context(
    output: Path,
) -> tuple[tuple[str, ...], dict[str, str], dict[str, dict]]:
    from founderos_atlas.config_memory import extract_facts

    configs = output / "configs"
    try:
        configured = tuple(
            sorted(
                (entry.name for entry in configs.iterdir() if entry.is_dir()),
                key=str.casefold,
            )
        )
    except OSError:
        configured = ()

    changes: dict[str, str] = {}
    routing_facts: dict[str, dict] = {}
    for hostname in configured:
        path = configs / hostname / "running_config.txt"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if text.strip():
            routing_facts[hostname] = extract_facts(text).view()
    report = load_json(output / "config_change_report.json") or {}
    rows = report.get("reports") or ()
    if isinstance(rows, list | tuple):
        for row in rows:
            if not isinstance(row, dict):
                continue
            hostname = row.get("hostname")
            change_count = row.get("change_count")
            if isinstance(hostname, str) and isinstance(change_count, int):
                changes[hostname] = f"{change_count} change(s)"
    return configured, changes, routing_facts


def _refresh_current_topology_viewer(
    output: Path,
    *,
    workspace_root: str | Path,
    last_discovered: str | None = None,
    force: bool = False,
) -> bool:
    """Refresh one current viewer from its adjacent immutable snapshot.

    Only the live scope root is accepted by callers. History repositories are
    never traversed or rewritten; their viewer remains the record of what that
    discovery produced at the time.
    """

    viewer_path = output / "atlas_topology.html"
    try:
        override_revision = SiteOverrideRepository(workspace_root).load().revision
        identity_revision = PeerResolutionRepository(workspace_root).load().revision
    except AtlasWorkspaceError:
        # Preserve an existing readable viewer when workspace state is
        # corrupt; the curation API will report the underlying error.
        return False
    if (
        not force
        and _viewer_has_current_visual_style(viewer_path)
        and _viewer_has_site_override_revision(
            viewer_path, override_revision, identity_revision
        )
    ):
        return False

    snapshot_data = load_json(output / "topology_snapshot.json")
    if snapshot_data is None:
        return False
    # One same-directory temporary per attempt keeps ``replace`` atomic while
    # also making simultaneous browser requests unable to clobber each
    # other's in-progress render.
    temporary_path = viewer_path.with_name(
        f".{viewer_path.name}.{uuid4().hex}.refreshing"
    )
    try:
        snapshot = TopologySnapshot.from_dict(snapshot_data)
        configured, config_changes, routing_facts = (
            _configuration_viewer_context(output)
        )
        workspace = Path(workspace_root)
        html = TopologyRenderer(
            snapshot,
            change_report=load_json(output / "change_report.json"),
            viewer_context={
                "last_discovered": last_discovered
                or snapshot.created_at
                or "unrecorded",
                "configured_hostnames": configured,
                "config_changes": config_changes,
                "routing_facts": routing_facts,
            },
            # Refreshes run inside the app's injected workspace, which can be
            # different from the process default in tests and embeddings.  A
            # viewer must retain its site-level topology when its style is
            # upgraded.
            site_catalog=SiteCatalogRepository(workspace).load(),
            site_overrides=SiteOverrideRepository(workspace).load(),
            identity_resolutions=PeerResolutionRepository(workspace).load(),
        ).render()
        temporary_path.write_text(html, encoding="utf-8")
        temporary_path.replace(viewer_path)
    except (AtlasWorkspaceError, KeyError, OSError, TypeError, ValueError):
        # A bad current snapshot must not destroy a still-readable old viewer
        # or turn the surrounding topology page into a server error.
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _topology_operational_facts(
    output: Path,
    *,
    workspace_root: str | Path,
    last_discovered: str | None = None,
) -> dict | None:
    """Canonical topology facts for one scope, straight off the renderer.

    The SAME renderer that draws the viewer computes these — the page
    header, the tables, and the viewer summary line can never disagree,
    because they are one calculation (topology/vocabulary.py).
    """

    snapshot_data = load_json(output / "topology_snapshot.json")
    if snapshot_data is None:
        return None
    try:
        from founderos_atlas.topology.vocabulary import DEFINITIONS

        snapshot = TopologySnapshot.from_dict(snapshot_data)
        configured, config_changes, routing_facts = (
            _configuration_viewer_context(output)
        )
        workspace = Path(workspace_root)
        resolution_repo = PeerResolutionRepository(workspace)
        resolution_catalog = resolution_repo.load()
        renderer = TopologyRenderer(
            snapshot,
            viewer_context={
                "last_discovered": last_discovered
                or snapshot.created_at
                or "unrecorded",
                "configured_hostnames": configured,
                "config_changes": config_changes,
                "routing_facts": routing_facts,
            },
            site_catalog=SiteCatalogRepository(workspace).load(),
            site_overrides=SiteOverrideRepository(workspace).load(),
            identity_resolutions=resolution_catalog,
        )
        elements = renderer.elements()
        site_view = renderer.site_view(elements)
        routing_view = renderer.routing_view(elements)
        counts = renderer.relationship_summary(
            elements, site_membership=site_view.get("membership")
        )
        devices = tuple(
            device for device in snapshot_data.get("devices") or ()
            if isinstance(device, dict)
        )
        unresolved = []
        for node in elements["nodes"]:
            data = node["data"]
            if data.get("kind") != "observed":
                continue
            unresolved.append({
                "peer": str(data.get("label") or data.get("id")),
                "observed_via": data.get("observed_via"),
                "observation": data.get("observation"),
                "router_id": data.get("router_id"),
                "management_ip": data.get("management_ip"),
                "why_unresolved": (
                    "announced through "
                    + str(data.get("observed_via") or "protocol evidence")
                    + " only — no discovered device owns this identity"
                ),
                "candidates": resolution_candidates(data, devices),
            })
        identity = {
            "revision": resolution_catalog.revision,
            "active": [
                item.to_dict() for item in resolution_catalog.resolutions
            ],
            "unresolved": sorted(unresolved, key=lambda item: item["peer"]),
            "history": [
                event.to_dict() for event in resolution_repo.history()[-12:]
            ],
            "device_options": sorted(
                {str(device.get("hostname") or "") for device in devices} - {""}
            ),
        }
        return {
            "counts": counts,
            "definitions": DEFINITIONS,
            "site_view": site_view,
            "routing_view": routing_view,
            "identity": identity,
            "observed_at": snapshot.created_at,
        }
    except (AtlasWorkspaceError, KeyError, OSError, TypeError, ValueError):
        return None


def register_routes(app) -> None:
    def current_actor() -> str:
        """The authenticated username for audit trails ("local-operator"
        in local development mode)."""

        from flask import g as _g

        principal = getattr(_g, "principal", None)
        return principal.username if principal else "local-operator"

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
        try:
            preferences = AdministrationRepository(
                cfg("ATLAS_WORKSPACE_ROOT")
            ).preferences()
        except Exception:
            preferences = None
        from .models import visible_nav_groups

        return {
            "nav_groups": visible_nav_groups(app),
            "active": active,
            "active_group": nav_group_for(active),
            "product": "Atlas",
            "ui_theme": preferences.theme if preferences else "system",
            "ui_density": preferences.density if preferences else "comfortable",
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
        """Resolve the selected scope: ?scope= wins, then session, then All.

        A URL-carried scope that no longer exists is answered EXPLICITLY:
        the page falls back to the Enterprise view and says so, rather than
        silently substituting whatever this browser last looked at — a
        pasted link must never quietly show a different scope than it
        names. Authorization is enforced before this resolver runs; the
        resolver itself only selects among already-authorized scope views.)
        """

        requested = request.args.get("scope", "").strip()
        if requested == GLOBAL_SCOPE_ID or requested in scopes:
            session["scope"] = requested
            return requested
        if requested:
            if not request.path.startswith("/api/"):
                flash(
                    f"The scope '{requested}' in this link no longer exists "
                    "— showing the Enterprise view instead.",
                    "warning",
                )
            session["scope"] = GLOBAL_SCOPE_ID
            return GLOBAL_SCOPE_ID
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

    def enterprise_routing_facts(graph, profiles) -> dict[str, dict]:
        by_name: dict[str, dict] = {}
        for profile in profiles:
            scope = profile_scope(output_dir(), profile.profile_id, profile.name)
            _configured, _changes, facts = _configuration_viewer_context(
                scope.output_dir
            )
            for hostname, value in facts.items():
                by_name.setdefault(hostname.casefold(), value)
        merged: dict[str, dict] = {}
        for device in graph.devices:
            for name in (device.hostname, *device.aliases):
                value = by_name.get(str(name).casefold())
                if value is not None:
                    merged[device.hostname] = value
                    break
        return merged

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
            catalog = SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load()
            overrides = SiteOverrideRepository(
                cfg("ATLAS_WORKSPACE_ROOT")
            ).load()
            snapshot = (
                write_enterprise_artifacts(
                    output_dir(), graph,
                    site_catalog=catalog,
                    site_overrides=overrides,
                    viewer_context={
                        "routing_facts": enterprise_routing_facts(
                            graph, profiles
                        )
                    },
                ).to_dict()
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

    def refresh_scope_topology_viewer(
        scope: DiscoveryScope, *, force: bool = False
    ) -> bool:
        profile = profile_for_scope(scope.scope_id)
        return _refresh_current_topology_viewer(
            scope.output_dir,
            workspace_root=cfg("ATLAS_WORKSPACE_ROOT"),
            last_discovered=(profile.last_discovery if profile is not None else None),
            force=force,
        )

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

    def _policy_store_fingerprint(store_dir: Path) -> tuple:
        """Identity of everything a policy evaluation reads: the store's
        mutable index files (blobs are content-addressed and immutable —
        any change to evidence rewrites these indexes) plus the Atlas
        version, so an upgrade with new policies re-evaluates."""

        from founderos_atlas.release import VERSION

        parts: list[tuple] = [("atlas", VERSION)]
        for name in (
            "sessions.json",
            "snapshots.json",
            "evidence/records.json",
            "evidence/observations.json",
        ):
            try:
                stamp = (store_dir / name).stat()
                parts.append((name, stamp.st_size, stamp.st_mtime_ns))
            except OSError:
                parts.append((name, None, None))
        return tuple(parts)

    # scope_id -> (fingerprint, summary). Derived workspace data, identical
    # for every operator (no user input reaches the evaluation), so a
    # process-level cache leaks nothing between users. Invalidation is
    # deterministic: any evidence write changes the fingerprint.
    _policy_summary_cache: dict[str, tuple[tuple, dict | None]] = {}

    def policy_summary_for(scope) -> dict | None:
        """Aggregate policy verdict counts for the canonical health model,
        or ``None`` when the policy engine has nothing to say (no memory).

        Re-running the full policy engine on every Home render cost ~4.4 s
        against a real workspace (480 evaluations re-reading the evidence
        store); the fingerprint cache keeps warm renders honest AND fast.
        """

        store_dir = scope.output_dir / "enterprise-memory"
        if not store_dir.is_dir():
            return None
        fingerprint = _policy_store_fingerprint(store_dir)
        cached = _policy_summary_cache.get(scope.scope_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        try:
            from founderos_atlas.policy import PolicyEngine

            report = PolicyEngine().evaluate_scopes(
                [(scope.label, memory_service(scope))], scope_label=scope.label
            )
        except Exception:  # noqa: BLE001 - health degrades, pages never 500
            return None
        summary: dict | None
        if report.total == 0:
            summary = None
        else:
            summary = {
                "total": report.total,
                "judged": report.judged,
                "passed": report.passed,
                "failed": report.failed,
                "warnings": report.warnings,
                "unknown": report.unknown,
                "generated_at": report.generated_at,
            }
        _policy_summary_cache[scope.scope_id] = (fingerprint, summary)
        return summary

    def health_for(scope, summary) -> "HealthAssessment":
        """The canonical health assessment for one scope (see health/)."""

        from founderos_atlas.health import assess_network_health

        out = scope.output_dir
        return assess_network_health(
            scope_id=scope.scope_id,
            scope_label=scope.label,
            now=now_iso(),
            snapshot=load_json(out / "topology_snapshot.json"),
            configurations_collected=summary.configurations_collected,
            config_change_report=load_json(out / "config_change_report.json"),
            state_change_report=load_json(out / "state_change_report.json"),
            incident_report=load_json(out / "incident_report.json"),
            policy_summary=policy_summary_for(scope),
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
        summary = summary_for(scope)
        return render_template(
            "dashboard.html",
            summary=summary,
            health=health_for(scope, summary).to_dict(),
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

        from founderos_atlas.health import aggregate_assessments

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
        # Canonical enterprise health: per-network assessments, aggregated
        # worst-of per dimension — the same definitions every page uses.
        health = aggregate_assessments(
            [
                health_for(scope, network.summary)
                for scope, network in zip(aggregated, networks)
            ],
            scope_id=GLOBAL_SCOPE_ID,
            scope_label=GLOBAL_SCOPE_LABEL,
            generated_at=now_iso(),
        ).to_dict()
        recent, _ = merged_history_rows(aggregated)
        graph, _snapshot = enterprise_world()
        now = now_iso()

        # Compass plans (advisor state, straight from the repository).
        repository = PlanRepository(output_dir())
        plans = []
        draft_plan_count = 0
        for plan in repository.list_plans():
            if plan.archived is not None:
                # "Taken care of": archived plans stay in history and
                # audit but never nag from Home again.
                continue
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
        # The canonical health assessment is authoritative (audit-2 High
        # #2): every degraded/critical dimension becomes an attention
        # item, so a Degraded banner can never sit above "nothing needs
        # your attention". Freshness stays with the richer
        # per-contribution recommendations when those exist.
        from .mission import attention_from_health

        has_stale_recs = any(
            c.fresh is False for c in graph.contributions
        )
        health_items = attention_from_health(
            health,
            skip=(
                frozenset({"discovery-freshness"}) if has_stale_recs
                else frozenset()
            ),
        )
        seen_keys = {
            (item["href"], item["text"]) for item in health_items
        }
        recommendations = health_items + [
            rec for rec in recommendations
            if (rec["href"], rec["text"]) not in seen_keys
        ]
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
        # Continue Working is a personal workbench: a per-user "clean
        # slate" stores a cutoff instant (nothing is deleted — history,
        # Compass, and audit keep everything) and only items updated
        # after it reappear here.
        from founderos_atlas.workspace.user_preferences import (
            UserPreferenceStore,
        )

        cleared_value = UserPreferenceStore(
            cfg("ATLAS_WORKSPACE_ROOT")
        ).ui_value(current_actor(), "workflow:continue-cleared") or {}
        cleared_at = str(cleared_value.get("at") or "")

        def _first_after(items, stamp_of):
            for item in items:
                if str(stamp_of(item) or "") > cleared_at:
                    return item
            return None

        continue_working = {
            "plan": _first_after(
                plans,
                lambda entry: entry["plan"].updated_at
                or entry["plan"].created_at,
            ),
            "investigation": _first_after(
                investigations, lambda entry: entry.get("generated_at")
            ),
            "prediction": _first_after(
                predictions, lambda entry: entry.get("generated_at")
            ),
            "cleared_at": cleared_at,
        }

        return render_template(
            "mission.html",
            summary=summary,
            health=health,
            recent=recent[:6],
            plans=plans,
            investigations=investigations,
            predictions=predictions[:4],
            continue_working=continue_working,
            change_rows=change_rows,
            recommendations=recommendations,
            freshness_ages=freshness_ages,
            activity=activity,
            **(enterprise_context(graph) if graph.devices else {}),
            **context,
        )

    @app.route("/home/continue-working/clear", methods=["POST"])
    def continue_working_clear():
        """Personal clean slate for the Continue Working card. Stores a
        per-user cutoff instant; nothing is deleted anywhere — plans stay
        in Compass, investigations in Paths history, predictions in
        Predict, and every audit record remains."""

        from founderos_atlas.workspace.user_preferences import (
            UserPreferenceStore,
        )

        UserPreferenceStore(cfg("ATLAS_WORKSPACE_ROOT")).set_ui_value(
            current_actor(), "workflow:continue-cleared",
            {"at": now_iso()},
        )
        flash(
            "Continue Working cleared for you — everything stays in "
            "Compass, Paths, and Predict; new work will reappear here.",
            "success",
        )
        return redirect(safe_redirect_target(request.form.get("next"), "/"))

    # -- Profiles -----------------------------------------------------------

    def _profile_audit(operation: str, subject: str, *, before=None, after=None, reason=None):
        from founderos_atlas.audit import AuditEvent, AuditLog
        return AuditLog(cfg("ATLAS_WORKSPACE_ROOT")).append(AuditEvent.create(
            category="discovery-profile", operation=operation, subject=subject,
            scope_id="all", before=before or {}, after=after or {}, reason=reason,
        ))

    @app.route("/profiles")
    def profiles():
        # Management lists every observation point, archived included, and
        # surfaces evidence-based duplicate-network candidates (PR-043.9).
        rows = [
            profile_row(p)
            for p in profile_service().list_profiles(include_archived=True)
        ]
        now = datetime.now(timezone.utc)
        for row in rows:
            stamp = row.get("last_discovery_iso")
            age_hours = None
            if stamp:
                try:
                    observed = datetime.fromisoformat(stamp)
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                    age_hours = max(0, int((now - observed).total_seconds() // 3600))
                except (TypeError, ValueError):
                    pass
            row["freshness"] = "never" if age_hours is None else (
                "fresh" if age_hours < 24 else f"stale · {age_hours}h"
            )
            row["health"] = "archived" if row["archived"] else (
                "unknown" if age_hours is None else ("ready" if age_hours < 24 else "stale")
            )
        query = (request.args.get("q") or "").strip().casefold()
        status = (request.args.get("status") or "").strip().casefold()
        tag = (request.args.get("tag") or "").strip().casefold()
        if query:
            rows = [row for row in rows if query in " ".join((
                row["name"], row["site"], row["owner"], row["description"],
                " ".join(row["tags"]), row["seed_label"],
            )).casefold()]
        if status == "active":
            rows = [row for row in rows if not row["archived"]]
        elif status == "archived":
            rows = [row for row in rows if row["archived"]]
        if tag:
            rows = [row for row in rows if tag in {t.casefold() for t in row["tags"]}]
        resolution = network_resolution()
        return render_template(
            "profiles.html",
            profile_revision=profile_service().repository.revision(),
            profiles=rows,
            networks=[network.to_dict() for network in resolution.networks],
            duplicate_candidates=[
                candidate.to_dict()
                for candidate in resolution.duplicate_candidates
            ],
            filters={"q": query, "status": status, "tag": tag},
            all_tags=sorted({t for row in rows for t in row["tags"]}, key=str.casefold),
            **base_context("profiles"),
        )

    @app.route("/profiles/new")
    def profile_new():
        return render_template(
            "profile_form.html", mode="add", profile=None,
            credential_sets=credential_service().list_sets(),
            **base_context("profiles")
        )

    @app.route("/profiles", methods=["POST"])
    def profile_create():
        form = request.form
        try:
            created = profile_service().add_profile(
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
                credential_sets=tuple(form.getlist("credential_sets")) or _csv(form.get("credential_sets")),
                site_hint=(form.get("site_hint", "").strip() or None),
                domain_hint=(form.get("domain_hint", "").strip() or None),
                owner=(form.get("owner", "").strip() or None),
                tags=_csv(form.get("tags")),
            )
            _profile_audit("create", created.profile_id, after={
                "name": created.name, "owner": created.owner,
                "tags": list(created.tags), "credential_refs": list(created.credential_sets),
            }, reason="Discovery profile created")
        except (AtlasWorkspaceError, ValueError) as error:
            flash(str(error), "error")
            return render_template(
                "profile_form.html", mode="add", profile=None,
                credential_sets=credential_service().list_sets(),
                **base_context("profiles")
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
            profile_revision=profile_service().repository.revision(),
            mode="edit",
            profile=profile_row(profile),
            credential_sets=credential_service().list_sets(),
            **base_context("profiles"),
        )

    def _check_profile_revision():
        """Optimistic concurrency for profile mutations: a form that was
        rendered against an older catalog revision is refused with a 409
        instead of silently overwriting someone else's change."""

        from founderos_atlas.workspace.exceptions import ProfileConflictError

        raw = request.form.get("expected_revision", "")
        if raw == "":
            return
        try:
            expected = int(raw)
        except ValueError:
            return
        try:
            profile_service().repository.check_revision(expected)
        except ProfileConflictError as error:
            abort(409, description=str(error))

    @app.route("/profiles/<name>", methods=["POST"])
    def profile_update(name: str):
        form = request.form
        _check_profile_revision()
        try:
            boundary = _boundary_from_form(form)
            existing = profile_service().get_profile(name)
            updated = profile_service().update_profile(
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
                credential_sets=tuple(form.getlist("credential_sets")) or _csv(form.get("credential_sets")),
                site_hint=(form.get("site_hint", "").strip() or None),
                domain_hint=(form.get("domain_hint", "").strip() or None),
                owner=(form.get("owner", "").strip() or None),
                tags=_csv(form.get("tags")),
            )
            _profile_audit("update", updated.profile_id,
                before={"name": existing.name, "owner": existing.owner, "tags": list(existing.tags)},
                after={"name": updated.name, "owner": updated.owner, "tags": list(updated.tags)},
                reason=form.get("reason") or "Discovery profile updated")
        except (AtlasWorkspaceError, ValueError) as error:
            flash(str(error), "error")
            return redirect(url_for("profile_edit", name=name))
        flash("Profile updated.", "success")
        return redirect(url_for("profiles"))

    @app.route("/profiles/<name>/delete", methods=["POST"])
    def profile_delete(name: str):
        from .confirmation import require_confirmation

        confirmation = require_confirmation(
            title=f"Delete profile {name}",
            detail=(
                f"This removes the discovery profile {name!r} and its "
                "stored credential reference."
            ),
            consequence=(
                "The network's enterprise knowledge is unaffected if "
                "another profile observes it; the profile itself cannot "
                "be recovered."
            ),
        )
        if confirmation is not None:
            return confirmation
        _check_profile_revision()
        try:
            removed = profile_service().delete_profile(name)
            _profile_audit("delete", removed.profile_id,
                           before={"name": removed.name, "credential_ref": removed.credential_ref},
                           reason=request.form.get("reason") or "Operator confirmed deletion")
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
            _profile_audit("duplicate", clone.profile_id,
                           after={"name": clone.name, "source_name": name},
                           reason="Operator duplicated observation profile")
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
        _check_profile_revision()
        restore = request.form.get("restore") == "1"
        if not restore:
            from .confirmation import require_confirmation

            confirmation = require_confirmation(
                title=f"Archive profile {name}",
                detail=(
                    f"This archives the {name!r} observation profile and "
                    "removes it from active discovery and aggregation."
                ),
                consequence=(
                    "Collected network knowledge is retained and the profile "
                    "can be restored from the Profiles page."
                ),
            )
            if confirmation is not None:
                return confirmation
        try:
            changed = profile_service().archive_profile(name, archived=not restore)
            _profile_audit("restore" if restore else "archive", changed.profile_id,
                           after={"name": changed.name, "archived": changed.archived},
                           reason=request.form.get("reason") or "Profile lifecycle change")
            flash(
                "Profile restored." if restore else
                "Profile archived — hidden from discovery and enterprise "
                "aggregation. Its network knowledge is retained.",
                "success",
            )
        except AtlasWorkspaceError as error:
            flash(str(error), "error")
        return redirect(url_for("profiles"))

    @app.route("/profiles/<name>/test", methods=["POST"])
    def profile_test(name: str):
        """Validate profile readiness without contacting network devices."""
        try:
            profile = profile_service().get_profile(name)
            provider = profile_service().credential_provider
            readable = False
            if profile.credential_ref:
                secret = provider.get(profile.credential_ref)
                readable = bool(secret)
                secret = None
            for credential_set in credential_service().list_sets():
                if credential_set.set_id not in profile.credential_sets:
                    continue
                for entry in credential_set.entries:
                    secret = provider.get(entry.credential_ref)
                    readable = readable or bool(secret)
                    secret = None
            if not readable:
                raise AtlasWorkspaceError("No readable credential is associated with this profile.")
            flash(
                "Profile readiness verified: targets, boundaries, and secure-store references are valid. No device was contacted.",
                "success",
            )
            _profile_audit("readiness-test", profile.profile_id,
                           after={"result": "ready", "device_contacted": False},
                           reason="Targets, boundaries, and secure references validated")
        except (AtlasWorkspaceError, ValueError, OSError) as error:
            flash(f"Profile readiness check failed: {error}", "error")
        return redirect(url_for("profiles"))

    # -- Credential sets ------------------------------------------------------

    def credential_service() -> CredentialSetService:
        return CredentialSetService(
            CredentialSetRepository(cfg("ATLAS_WORKSPACE_ROOT")),
            profile_service().credential_provider,
        )

    @app.route("/credentials")
    def credentials():
        sets = credential_service().list_sets()
        rows = credential_set_rows(sets)
        profiles_using = {
            credential_set.set_id: sorted(
                p.name for p in profile_service().list_profiles(include_archived=True)
                if credential_set.set_id in p.credential_sets
            ) for credential_set in sets
        }
        # A conservative preview: equal priority plus unrestricted/identical
        # scope can make ordering surprising.  It does not expose a secret.
        conflicts = []
        for credential_set in sets:
            entries = list(credential_set.entries)
            for index, left in enumerate(entries):
                for right in entries[index + 1:]:
                    if left.priority == right.priority and (
                        left.scope.is_unrestricted or right.scope.is_unrestricted
                        or left.scope == right.scope
                    ):
                        conflicts.append({
                            "set": credential_set.name,
                            "left": left.label,
                            "right": right.label,
                            "priority": left.priority,
                        })
        provider = profile_service().credential_provider
        try:
            provider_available = provider.available()
        except Exception:
            provider_available = False
        return render_template(
            "credentials.html", credential_sets=rows,
            profiles=profile_service().list_profiles(include_archived=True),
            profiles_using=profiles_using, conflicts=conflicts,
            provider_name=type(provider).__name__, provider_available=provider_available,
            **base_context("credentials")
        )

    def _credential_audit(operation: str, subject: str, *, before=None, after=None, reason=None):
        from founderos_atlas.audit import AuditEvent, AuditLog
        return AuditLog(cfg("ATLAS_WORKSPACE_ROOT")).append(AuditEvent.create(
            category="credential-metadata", operation=operation,
            subject=subject, scope_id="all", before=before or {}, after=after or {},
            reason=reason,
        ))

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
                roles=_csv(form.get("roles")),
                profile_ids=tuple(form.getlist("profile_ids")),
                device_ids=_csv(form.get("device_ids")),
            )
            created = credential_service().add_entry(
                set_name=form.get("set_name", "").strip(),
                label=form.get("label", "").strip(),
                username=form.get("username", "").strip(),
                password=form.get("password", ""),
                priority=_int(form.get("priority"), 100),
                scope=scope,
                rotation_due_at=(form.get("rotation_due_at", "").strip() or None),
                expires_at=(form.get("expires_at", "").strip() or None),
            )
            entry = created.entries[-1]
            _credential_audit("create", f"{created.set_id}:{entry.entry_id}", after={
                "label": entry.label, "username": entry.username,
                "priority": entry.priority, "scope": entry.scope.to_dict(),
                "rotation_due_at": entry.rotation_due_at, "expires_at": entry.expires_at,
                "credential_ref": entry.credential_ref,
            }, reason="Credential reference created in secure provider")
            flash("Credential saved securely.", "success")
        except (AtlasWorkspaceError, ValueError) as error:
            flash(str(error), "error")
        return redirect(url_for("credentials"))

    @app.route("/credentials/<set_id>/<entry_id>/delete", methods=["POST"])
    def credentials_delete(set_id: str, entry_id: str):
        from .confirmation import require_confirmation

        confirmation = require_confirmation(
            title=f"Delete credential {entry_id}",
            detail=(
                f"This deletes credential entry {entry_id!r} from set "
                f"{set_id!r} AND its secret from the secure store."
            ),
            consequence="The stored secret cannot be recovered.",
        )
        if confirmation is not None:
            return confirmation
        impacted = [p.name for p in profile_service().list_profiles(include_archived=True)
                    if set_id in p.credential_sets]
        if impacted and request.form.get("confirm_impact") != "yes":
            flash(
                "Deletion blocked: this credential set is used by "
                + ", ".join(impacted)
                + ". Confirm the dependency warning before deleting.",
                "error",
            )
            return redirect(url_for("credentials"))
        credential_service().delete_entry(set_id, entry_id)
        _credential_audit("delete", f"{set_id}:{entry_id}",
                          before={"credential_ref": f"atlas-credset:{set_id}:{entry_id}"},
                          reason=request.form.get("reason") or "Operator confirmed deletion")
        flash("Credential deleted.", "success")
        return redirect(url_for("credentials"))

    @app.route("/credentials/<set_id>/<entry_id>/test", methods=["POST"])
    def credentials_test(set_id: str, entry_id: str):
        ok = credential_service().test_store_access(set_id, entry_id)
        _credential_audit("test", f"{set_id}:{entry_id}",
                          after={"result": "store-readable" if ok else "store-unavailable"},
                          reason="Secure-store reference check; no device contacted")
        flash(
            "Secure-store access verified. This does not test a device login."
            if ok else "The secure provider could not read this credential.",
            "success" if ok else "error",
        )
        return redirect(url_for("credentials"))

    @app.route(
        "/credentials/<set_id>/<entry_id>/test-connection", methods=["POST"]
    )
    def credentials_test_connection(set_id: str, entry_id: str):
        """Honest connection test against an EXPLICIT authorized target."""

        from founderos_atlas.transport import SSHDeviceTransport

        target = str(request.form.get("target") or "").strip()
        if not target:
            flash(
                "Enter the address of a device you are authorized to test "
                "against.",
                "error",
            )
            return redirect(url_for("credentials"))
        factory = cfg("ATLAS_TRANSPORT_FACTORY") or SSHDeviceTransport
        try:
            result = credential_service().test_connection(
                set_id, entry_id, target=target, transport_factory=factory,
            )
        except Exception as error:  # invalid set/entry or transport setup
            flash(str(error), "error")
            return redirect(url_for("credentials"))
        # Audit the target and outcome only — never the credential, the
        # command, or any device output.
        _credential_audit(
            "test-connection", f"{set_id}:{entry_id}",
            after={"target": target, "outcome": result.outcome,
                   "platform": result.platform},
            reason="Explicit connection test to an authorized target",
        )
        flash(
            f"Connection test → {result.outcome}: {result.detail}",
            "success" if result.succeeded else "error",
        )
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

        def optional_limit(name):
            """Blank means auto — the system suggests; typed values are
            bounded by resolve_plan's own validation."""

            value = form.get(name, "").strip()
            return int(value) if value.isdigit() else None

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
                timeout_seconds=optional_limit("timeout_seconds"),
                concurrency=optional_limit("concurrency"),
                exclusions=exclusions,
                allow_large_scan=form.get("allow_large_scan") == "yes",
            )
        except DiscoveryPlanError as error:
            return None, str(error)
        return plan, None

    def _wizard_plan_for_display(plan):
        """Add platform support context without changing execution.

        Seed and CIDR addresses have no platform evidence until the
        read-only identity probe. Imported rows may carry an operator hint,
        which is checked against the same registry discovery will use.
        """

        from founderos_atlas.platforms import default_registry

        registry = default_registry()
        payload = plan.to_dict()
        for candidate in payload["candidates"]:
            hint = candidate.get("platform_hint")
            driver = registry.driver_for(str(hint)) if hint else None
            if driver is not None:
                candidate["platform_support"] = (
                    f"Supported: {driver.display_name}"
                )
            elif hint:
                candidate["platform_support"] = (
                    f"Unsupported platform hint: {hint}"
                )
            else:
                candidate["platform_support"] = "Pending identity probe"
        payload["supported_platforms"] = list(registry.supported_platforms())
        return payload

    @app.route("/discovery/wizard")
    def discovery_wizard():
        drafts = AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        draft_id = (request.args.get("draft") or "").strip()
        return render_template(
            "discovery_wizard.html",
            credential_sets=credential_service().list_sets(),
            plan=None,
            error=None,
            draft_id=draft_id,
            draft=drafts.get_draft(draft_id) if draft_id else None,
            drafts=_drafts_newest_first(),
            **base_context("discovery"),
        )

    def _drafts_newest_first() -> dict:
        """Resume picker order: most recently updated draft first."""

        items = AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT")).drafts()
        # updated_at has second precision; the save-order sequence breaks
        # ties, so the most recently saved draft is always first.
        return dict(sorted(
            items.items(),
            key=lambda kv: (
                str((kv[1] or {}).get("updated_at") or ""),
                int((kv[1] or {}).get("sequence") or 0),
            ),
            reverse=True,
        ))

    @app.route("/api/discovery/wizard/drafts", methods=["POST"])
    def discovery_wizard_draft_save():
        json_body = request.get_json(silent=True)
        if isinstance(json_body, dict):
            # JSON preserves repeated fields as arrays (the autosave path).
            payload = dict(json_body)
        else:
            # Form-encoded: collect EVERY value per key so multi-select
            # fields (credential_sets) survive instead of being flattened.
            payload = {}
            for key in request.form:
                values = request.form.getlist(key)
                payload[key] = values if len(values) > 1 else values[0]
        forbidden = {"password", "secret", "token", "passphrase", "private_key"}
        safe = {
            key: value for key, value in payload.items()
            if str(key).casefold() not in forbidden
        }
        # Multi-value fields are always stored as lists so the template
        # membership test is exact (never substring) whether one or many
        # were selected.
        for multi_key in ("credential_sets",):
            if multi_key in safe and not isinstance(safe[multi_key], list):
                safe[multi_key] = [safe[multi_key]] if safe[multi_key] else []
        identifier = AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT")).save_draft(
            str(payload.get("draft_id") or "") or None, safe
        )
        return jsonify(draft_id=identifier, saved=True)

    @app.route("/discovery/wizard/drafts/<draft_id>/cancel", methods=["POST"])
    def discovery_wizard_draft_cancel(draft_id: str):
        from .confirmation import require_confirmation

        confirmation = require_confirmation(
            title="Remove discovery draft",
            detail=f"This removes the saved wizard draft {draft_id!r}.",
            consequence=(
                "No discovery will be started; the draft's targeting and "
                "boundary choices are discarded (drafts never held "
                "credentials)."
            ),
        )
        if confirmation is not None:
            return confirmation
        AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT")).delete_draft(draft_id)
        flash("Discovery draft cancelled and removed. No discovery was started.", "success")
        return redirect(url_for("discovery_wizard"))

    @app.route("/discovery/wizard/preview", methods=["POST"])
    def discovery_wizard_preview():
        plan, error = _wizard_plan_from_form(request.form)
        safe = {key: value for key, value in request.form.items()
                if key not in {"password", "secret", "token"}}
        safe["credential_sets"] = request.form.getlist("credential_sets")
        draft_id = AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT")).save_draft(
            request.form.get("draft_id") or None, safe
        )
        estimate = None
        if plan:
            estimate = max(1, round(
                len(plan.candidates) * plan.effective_timeout_seconds
                / max(1, plan.effective_concurrency) / 60
            ))
        return render_template(
            "discovery_wizard.html",
            credential_sets=credential_service().list_sets(),
            plan=_wizard_plan_for_display(plan) if plan else None,
            form=request.form,
            error=error,
            draft_id=draft_id,
            draft=safe,
            drafts=_drafts_newest_first(),
            estimate_minutes=estimate,
            **base_context("discovery"),
        )

    @app.route("/discovery/wizard/start", methods=["POST"])
    def discovery_wizard_start():
        plan, error = _wizard_plan_from_form(request.form)
        if plan is None:
            flash(error, "error")
            return redirect(url_for("discovery_wizard"))
        if request.form.get("dry_run") == "1":
            flash("Dry run complete. Candidates and safety checks were validated; no device was contacted.", "success")
            return redirect(url_for("discovery_wizard", draft=request.form.get("draft_id", "")))
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
                    concurrency=plan.concurrency,
                    connect_timeout_seconds=plan.timeout_seconds,
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
                    concurrency=plan.concurrency,
                    connect_timeout_seconds=plan.timeout_seconds,
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
        draft_id = request.form.get("draft_id", "").strip()
        if draft_id:
            AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT")).delete_draft(draft_id)
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

        repository = AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        setting = (
            repository.preferences().timezone
            if repository.preferences_path.is_file()
            else app.config.get("ATLAS_DISPLAY_TIMEZONE")
        )
        return resolve_timezone(setting)

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
        page = max(1, _page_arg())
        total_pages = max(1, -(-len(devices) // EVIDENCE_PAGE_SIZE))
        page = min(page, total_pages)
        visible_devices = devices[(page - 1) * EVIDENCE_PAGE_SIZE:page * EVIDENCE_PAGE_SIZE]

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
            devices=visible_devices, filters=filters, options=options,
            device_count=len(devices), page=page, total_pages=total_pages,
            filtered=any(filters.values()),
            record_count=len(records), visible_count=len(visible),
            totals=_evidence_storage_totals(scopes, scope_id),
            saved_filters=[f.to_dict() for f in _saved_filter_store().list(
                owner=current_actor(), surface="evidence")],
            current_query=_shareable_query(),
            **context,
        )

    def _saved_filter_store():
        from .saved_filters import SavedFilterStore

        return SavedFilterStore(cfg("ATLAS_WORKSPACE_ROOT"))

    def _shareable_query() -> str:
        from .saved_filters import _normalize_query

        return _normalize_query(request.query_string.decode("utf-8"))

    @app.route("/evidence/saved-filters", methods=["POST"])
    def evidence_saved_filter_create():
        from founderos_atlas.audit import AuditEvent, AuditLog

        store = _saved_filter_store()
        try:
            record = store.save(
                owner=current_actor(), surface="evidence",
                name=str(request.form.get("name") or ""),
                query=str(request.form.get("query") or ""),
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(safe_redirect_target(
                request.form.get("next"), url_for("evidence_page")
            ))
        AuditLog(cfg("ATLAS_WORKSPACE_ROOT")).append(AuditEvent.create(
            category="saved-filter", operation="save",
            subject=f"evidence-filter:{record.filter_id}",
            actor=current_actor(),
            after={"name": record.name}, correlation_id=g.correlation_id,
        ))
        flash(f"Filter '{record.name}' saved.", "success")
        return redirect(f"/evidence?{record.query}" if record.query
                        else url_for("evidence_page"))

    @app.route("/evidence/saved-filters/<filter_id>/rename", methods=["POST"])
    def evidence_saved_filter_rename(filter_id: str):
        try:
            renamed = _saved_filter_store().rename(
                filter_id, owner=current_actor(),
                name=str(request.form.get("name") or ""),
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("evidence_page"))
        flash("Filter renamed." if renamed else "No such saved filter.",
              "success" if renamed else "error")
        return redirect(safe_redirect_target(
            request.form.get("next"), url_for("evidence_page")
        ))

    @app.route("/evidence/saved-filters/<filter_id>/delete", methods=["POST"])
    def evidence_saved_filter_delete(filter_id: str):
        from founderos_atlas.audit import AuditEvent, AuditLog

        removed = _saved_filter_store().delete(
            filter_id, owner=current_actor()
        )
        if removed:
            AuditLog(cfg("ATLAS_WORKSPACE_ROOT")).append(AuditEvent.create(
                category="saved-filter", operation="delete",
                subject=f"evidence-filter:{filter_id}",
                actor=current_actor(), correlation_id=g.correlation_id,
            ))
        flash("Filter deleted." if removed else "No such saved filter.",
              "success" if removed else "error")
        return redirect(safe_redirect_target(
            request.form.get("next"), url_for("evidence_page")
        ))

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

    # -- Enterprise Policy (PR-047 SENTINEL; PR-053 scale) ------------------

    # The engine's report is deterministic over the memories it read, so
    # one in-process cache entry keyed on the memory stamps keeps the page
    # fast across the paginated/filtered requests an investigation makes.
    _policy_report_cache: dict = {"key": None, "report": None}

    def _policy_cache_key(scopes, scope_id) -> tuple:
        parts: list[tuple] = [("scope", scope_id)]
        for scope in memory_scopes(scopes, scope_id):
            records = (
                scope.output_dir / "enterprise-memory" / "evidence"
                / "records.json"
            )
            configs = (
                scope.output_dir / "enterprise-memory" / "configurations"
                / "index.json"
            )
            for path in (records, configs):
                try:
                    stat = path.stat()
                    parts.append((str(path), stat.st_mtime_ns, stat.st_size))
                except OSError:
                    parts.append((str(path), None))
        return tuple(parts)

    def _policy_report_dict(scopes, scope_id, scope_label) -> dict:
        from founderos_atlas.policy import PolicyEngine

        key = _policy_cache_key(scopes, scope_id)
        if _policy_report_cache["key"] == key:
            return _policy_report_cache["report"]
        report = PolicyEngine().evaluate_scopes(
            [
                (scope.label, memory_service(scope))
                for scope in memory_scopes(scopes, scope_id)
            ],
            scope_label=scope_label,
        )
        report_dict = report.to_dict()
        _policy_report_cache.update(key=key, report=report_dict)
        return report_dict

    def _device_maps() -> tuple[dict, dict]:
        """hostname → site and hostname → platform, from the graph."""

        graph, _snapshot = enterprise_world()
        sites: dict[str, str] = {}
        platforms: dict[str, str] = {}
        for row in get_enterprise_inventory(graph):
            hostname = str(row.get("hostname") or "")
            if hostname:
                sites[hostname] = str(row.get("site") or "unknown")
                platforms[hostname] = str(row.get("platform") or "unknown")
        return sites, platforms

    def _policy_rows(scopes, scope_id, scope_label):
        """Annotated, investigation-ready rows plus their supporting state."""

        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.policy.exceptions import PolicyExceptionRepository
        from founderos_atlas.policy.explorer import annotate_evaluations

        report_dict = _policy_report_dict(scopes, scope_id, scope_label)
        workspace = cfg("ATLAS_WORKSPACE_ROOT")
        now = now_iso()
        exception_repo = PolicyExceptionRepository(workspace)
        active_subjects = exception_repo.active_subjects(now)
        assignments = AnnotationStore(workspace).all("policy-assignment")
        owners = {
            subject: str(fields.get("owner") or "")
            for subject, fields in assignments.items()
        }
        sites, platforms = _device_maps()
        rows = annotate_evaluations(
            report_dict["evaluations"],
            now=now,
            exception_subjects=active_subjects,
            sites_by_device=sites,
            platforms_by_device=platforms,
            owners_by_subject=owners,
            assignments_by_subject=assignments,
        )
        return rows, report_dict, exception_repo

    def _resolve_identity_filters(filters):
        """"Assigned to me" resolves from the authenticated principal on
        the server; a client-supplied owner param never impersonates it."""

        if filters.assigned_to_me:
            from dataclasses import replace as _replace

            return _replace(filters, owner=current_actor())
        return filters

    @app.route("/policy")
    def policy_page():
        """Enterprise Policy at scale (PR-053).

        The engine's verdicts stay authoritative; this page is an
        INVESTIGATION over them — filtered, grouped, and paginated
        server-side, so a thousand-device estate renders one page of
        result rows, never a thousand expanded reasoning bodies. Every
        filter lives in the URL and is therefore shareable; the full
        reasoning body renders on each result's own page.
        """

        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.policy import list_packs
        from founderos_atlas.policy.explorer import (
            EFFECTIVE_STATUSES,
            STATUS_LABELS,
            ResultFilter,
            filter_rows,
            group_rows,
            heatmap,
            paginate,
            posture_score,
            sort_rows,
            summarize,
        )
        from founderos_atlas.policy.trend import PolicyTrend

        from .timefmt import format_timestamp

        context, scopes, scope_id = scoped_context("policy")
        rows, report_dict, _repo = _policy_rows(
            scopes, scope_id, context["active_scope_label"]
        )
        filters = ResultFilter.from_args(request.args)
        effective_filters = _resolve_identity_filters(filters)
        filtered = sort_rows(filter_rows(rows, effective_filters))
        page = paginate(filtered, filters.page, filters.per_page)

        # Assignment-batch context (audit-3 Inbox actionability): resolve
        # the batch from the audited annotations so the banner can say who
        # assigned, when, and — honestly — whether any of the originally
        # assigned results no longer carry this assignment. The filter
        # itself only narrows rows the caller is already authorized to
        # see, so a guessed correlation id reveals nothing new.
        assignment_context = None
        if filters.assignment:
            in_batch = [
                row for row in rows
                if str(row.get("assignment_correlation") or "")
                == filters.assignment
            ]
            original = max(
                (
                    int((AnnotationStore(cfg("ATLAS_WORKSPACE_ROOT")).get(
                        "policy-assignment", str(row.get("subject") or "")
                    ) or {}).get("batch_size") or 0)
                    for row in in_batch
                ),
                default=0,
            )
            newest = max(
                (str(row.get("assigned_at") or "") for row in in_batch),
                default="",
            )
            assignment_context = {
                "matching": len(in_batch),
                "visible": len(filtered),
                "original": original,
                "assigned_by": next(
                    (str(row.get("assigned_by") or "")
                     for row in in_batch), "",
                ),
                "assigned_at": newest,
                "missing": max(0, original - len(in_batch)),
                "clear_href": scoped_url("/policy", scope_id),
            }
        groups = (
            group_rows(filtered, filters.group_by)
            if filters.group_by else []
        )

        # Record the trend point (only when posture changed) and read the
        # series for the sparkline. Score and trend both use the effective
        # buckets the tiles display, so every number on the page reconciles.
        overall = summarize(rows)
        posture = posture_score(overall)
        trend = PolicyTrend(cfg("ATLAS_WORKSPACE_ROOT"))
        _series_before = trend.series(scope_id)
        _recorded = trend.record(
            scope_id=scope_id,
            recorded_at=report_dict["generated_at"],
            score=posture["score"],
            passed=overall["pass"],
            failed=overall["fail"],
            warnings=overall["warning"],
            unknown=overall["unknown"] + overall["missing-evidence"],
        )
        if (
            _recorded and _series_before
            and overall["fail"] > int(_series_before[-1].get("failed") or 0)
        ):
            try:
                from founderos_atlas.notifications import (
                    KIND_POLICY_REGRESSION, NotificationStore,
                )

                NotificationStore(cfg("ATLAS_WORKSPACE_ROOT")).notify(
                    kind=KIND_POLICY_REGRESSION,
                    title=(
                        f"Compliance regressed: {overall['fail']} failure(s) "
                        f"(was {int(_series_before[-1].get('failed') or 0)})"
                    ),
                    detail=f"Scope: {context['active_scope_label']}.",
                    href=scoped_url("/policy", scope_id, status="fail"),
                    audience="role:policy-manager",
                    dedupe_key=f"policy-regression:{scope_id}",
                )
            except OSError:
                pass

        option_policies = sorted(
            {
                (
                    str((row.get("policy") or {}).get("policy_id")),
                    str((row.get("policy") or {}).get("name")),
                )
                for row in rows
            },
            key=lambda pair: pair[1].casefold(),
        )
        return render_template(
            "policy.html",
            report=report_dict,
            filters=filters,
            filter_args=filters.to_args(),
            assignment_context=assignment_context,
            current_username=current_actor(),
            page=page,
            groups=groups,
            summary=summarize(filtered),
            overall=overall,
            posture=posture,
            heatmap=heatmap(rows),
            trend=trend.series(scope_id)[-12:],
            statuses=EFFECTIVE_STATUSES,
            status_labels=STATUS_LABELS,
            option_policies=option_policies,
            option_sites=sorted({str(r.get("site")) for r in rows} - {""}),
            option_platforms=sorted(
                {str(r.get("platform")) for r in rows} - {""}
            ),
            option_severities=sorted(
                {str((r.get("policy") or {}).get("severity")) for r in rows}
                - {""}
            ),
            packs=[p.to_dict() for p in list_packs()],
            generated_at=format_timestamp(
                report_dict["generated_at"], tz=display_timezone()
            ),
            **context,
        )

    @app.route("/policy/result/<policy_id>/<path:hostname>")
    def policy_result_page(policy_id: str, hostname: str):
        """One verdict, fully disclosed: reasoning, evidence, confidence,
        remediation, exception state, and ownership — the heavy body that
        the list page deliberately no longer renders."""

        context, scopes, scope_id = scoped_context("policy")
        rows, _report, exception_repo = _policy_rows(
            scopes, scope_id, context["active_scope_label"]
        )
        wanted = hostname.casefold()
        evaluation = next(
            (
                row for row in rows
                if str((row.get("policy") or {}).get("policy_id")) == policy_id
                and str(row.get("hostname") or "").casefold() == wanted
            ),
            None,
        )
        if evaluation is None:
            flash(
                f"No result for policy '{policy_id}' on '{hostname}' exists "
                "in this scope — the estate may have changed since this "
                "link was made.",
                "warning",
            )
            return redirect(scoped_url("/policy", scope_id))
        from founderos_atlas.policy.explorer import result_subject

        exception = exception_repo.find(
            result_subject(policy_id, evaluation["hostname"])
        )
        return render_template(
            "policy_result.html",
            e=evaluation,
            exception=exception.to_dict() if exception else None,
            exception_active=(
                exception.is_active(now_iso()) if exception else False
            ),
            exception_revision=exception_repo.revision(),
            **context,
        )

    @app.route("/policy/export.csv")
    def policy_export():
        """The FILTERED result set as CSV — same query params as the page."""

        import csv
        import io

        from founderos_atlas.policy.explorer import (
            ResultFilter,
            export_rows,
            filter_rows,
            sort_rows,
        )

        context, scopes, scope_id = scoped_context("policy")
        rows, _report, _repo = _policy_rows(
            scopes, scope_id, context["active_scope_label"]
        )
        filters = _resolve_identity_filters(ResultFilter.from_args(request.args))
        exported = export_rows(sort_rows(filter_rows(rows, filters)))
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=list(exported[0].keys()) if exported else [
                "policy_id", "policy", "category", "severity", "device",
                "site", "platform", "status", "owner", "evidence_fresh",
                "conclusion", "network",
            ],
        )
        writer.writeheader()
        writer.writerows(exported)
        return app.response_class(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                    "attachment; filename=policy-results.csv"
            },
        )

    def _check_exception_revision(repo) -> None:
        from founderos_atlas.policy.exceptions import (
            PolicyExceptionConflictError,
        )

        raw = request.form.get("expected_revision", "")
        if raw == "":
            return
        try:
            repo.check_revision(int(raw))
        except PolicyExceptionConflictError as error:
            abort(409, description=str(error))
        except ValueError:
            pass

    @app.route("/policy/exceptions", methods=["POST"])
    def policy_exception_grant():
        from founderos_atlas.policy.exceptions import PolicyExceptionRepository

        repo = PolicyExceptionRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        _check_exception_revision(repo)
        try:
            repo.grant(
                actor=current_actor(),
                policy_id=str(request.form.get("policy_id") or ""),
                hostname=str(request.form.get("hostname") or ""),
                reason=str(request.form.get("reason") or ""),
                owner=str(request.form.get("owner") or ""),
                approved_by=str(request.form.get("approved_by") or "") or None,
                expires_at=str(request.form.get("expires_at") or "") or None,
                occurred_at=now_iso(),
            )
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash(
                "Exception granted — the result is reclassified as Excepted "
                "until it expires or is revoked, and the grant is audited.",
                "success",
            )
        return redirect(safe_redirect_target(
            request.form.get("next"), scoped_url("/policy")
        ))

    @app.route("/policy/exceptions/revoke", methods=["POST"])
    def policy_exception_revoke():
        from founderos_atlas.policy.exceptions import PolicyExceptionRepository

        repo = PolicyExceptionRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        _check_exception_revision(repo)
        try:
            repo.revoke(
                actor=current_actor(),
                policy_id=str(request.form.get("policy_id") or ""),
                hostname=str(request.form.get("hostname") or ""),
                reason=str(request.form.get("reason") or "") or None,
                occurred_at=now_iso(),
            )
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash("Exception revoked — the engine's verdict stands again.",
                  "success")
        return redirect(safe_redirect_target(
            request.form.get("next"), scoped_url("/policy")
        ))

    def _scope_from_next(next_value) -> str:
        """The scope the operator was looking at, read from the posted
        return URL (a POST has no ?scope=). Unknown values fall back to
        the Enterprise view — never to whatever the session remembers."""

        from urllib.parse import parse_qs, urlsplit

        try:
            candidates = parse_qs(
                urlsplit(str(next_value or "")).query
            ).get("scope") or []
        except ValueError:
            candidates = []
        requested = str(candidates[0]).strip() if candidates else ""
        if requested and (
            requested == GLOBAL_SCOPE_ID or requested in known_scopes()
        ):
            return requested
        return GLOBAL_SCOPE_ID

    @app.route("/policy/assign", methods=["POST"])
    def policy_assign():
        """Bulk ownership: the selected results get an owner, audited under
        one correlation id.

        The notification must let the recipient act without detective
        work: a single assignment names the policy, device, verdict and
        severity and links to the exact verdict page; a batch links to a
        server-side ?assignment=<correlation> filter resolved from the
        audited annotations — never an unbounded subject list in a URL,
        never browser-local state."""

        from uuid import uuid4

        from founderos_atlas.audit import AnnotationStore

        owner = str(request.form.get("owner") or "").strip()
        subjects = [
            subject for subject in request.form.getlist("subjects")
            if str(subject or "").strip()
        ]
        if not owner or not subjects:
            flash("Select at least one result and name an owner.", "error")
            return redirect(safe_redirect_target(
                request.form.get("next"), scoped_url("/policy")
            ))
        scope_id = _scope_from_next(request.form.get("next"))
        scopes = known_scopes()
        scope_label = (
            GLOBAL_SCOPE_LABEL if scope_id == GLOBAL_SCOPE_ID
            else scopes[scope_id].label
        )
        rows, _report, _repo = _policy_rows(scopes, scope_id, scope_label)
        by_subject = {str(row.get("subject") or ""): row for row in rows}

        store = AnnotationStore(cfg("ATLAS_WORKSPACE_ROOT"))
        correlation = f"bulk:{uuid4().hex}"
        already_owned = all(
            str((store.get("policy-assignment", subject) or {}).get("owner")
                or "") == owner
            for subject in subjects
        )
        for subject in subjects:
            # The correlation and batch size live IN the audited
            # annotation, so the batch is resolvable server-side after a
            # restart without a second copy of the assignment data.
            store.set(
                actor=current_actor(),
                kind="policy-assignment", subject=subject,
                fields={
                    "owner": owner,
                    "correlation": correlation,
                    "batch_size": len(subjects),
                },
                correlation_id=correlation,
                occurred_at=now_iso(),
            )

        def _describe(subject: str) -> str:
            row = by_subject.get(subject)
            if row is None:
                return subject.removeprefix("policy-result:")[:120]
            policy = row.get("policy") or {}
            name = str(policy.get("name") or policy.get("policy_id"))[:60]
            return f"{name} on {str(row.get('hostname') or 'unknown')[:60]}"

        if len(subjects) == 1:
            row = by_subject.get(subjects[0])
            policy = (row or {}).get("policy") or {}
            title = f"Policy assigned: {_describe(subjects[0])}"
            if row is not None:
                status = str(row.get("effective_status") or "unknown")
                severity = str(policy.get("severity") or "unknown")
                detail = (
                    f"{status.replace('-', ' ').capitalize()} · "
                    f"{severity.capitalize()} severity · {scope_label} · "
                    f"Assigned by {current_actor()}."
                )
                href = url_for(
                    "policy_result_page",
                    policy_id=str(policy.get("policy_id") or ""),
                    hostname=str(row.get("hostname") or ""),
                    scope=scope_id,
                )
            else:
                # The subject no longer evaluates in this scope; the batch
                # filter still resolves whatever remains authoritative.
                detail = f"{scope_label} · Assigned by {current_actor()}."
                href = scoped_url("/policy", scope_id, assignment=correlation)
        else:
            preview = "; ".join(
                _describe(subject) for subject in subjects[:3]
            )
            remaining = len(subjects) - 3
            if remaining > 0:
                preview += f"; and {remaining} more"
            title = f"{len(subjects)} policy results assigned to you"
            detail = f"{preview}. {scope_label} · Assigned by {current_actor()}."
            href = scoped_url("/policy", scope_id, assignment=correlation)

        if not already_owned:
            # A repeated identical assignment is audited but is not a new
            # event for the recipient — no duplicate unread notification.
            try:
                from founderos_atlas.notifications import (
                    KIND_ASSIGNMENT, NotificationStore,
                )

                NotificationStore(cfg("ATLAS_WORKSPACE_ROOT")).notify(
                    kind=KIND_ASSIGNMENT,
                    title=title,
                    detail=detail,
                    href=href,
                    audience=owner,
                    correlation_id=correlation,
                )
            except OSError:
                pass
        flash(
            f"{len(subjects)} result(s) assigned to {owner} "
            "(audited under one correlation id).",
            "success",
        )
        return redirect(safe_redirect_target(
            request.form.get("next"), scoped_url("/policy")
        ))

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

        # PR-053: the unified chronology — every event source, one filter
        # model, server-side pagination, exact-object links, provenance.
        from founderos_atlas.audit import unified_audit_events
        from founderos_atlas.compass import PlanRepository
        from founderos_atlas.policy.trend import PolicyTrend

        from .chronicle import (
            ChronicleFilter,
            chronicle_events,
            filter_events,
            summarize_kinds,
        )
        from founderos_atlas.listing import paginate

        report_scopes = (
            aggregation_scopes(scopes)
            if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],)
        )
        incident_reports = [
            (scope.label, load_json(scope.output_dir / "incident_report.json"))
            for scope in report_scopes
        ]
        prediction_reports = [
            (scope.label,
             load_json(scope.output_dir / "prediction_report.json"))
            for scope in report_scopes
        ]
        try:
            plans = [
                plan.to_dict()
                for plan in PlanRepository(output_dir()).list_plans()
            ]
        except Exception:  # noqa: BLE001 - plans are optional evidence
            plans = []
        trend_store = PolicyTrend(cfg("ATLAS_WORKSPACE_ROOT"))
        trend_points = [
            (scope.scope_id, point)
            for scope in report_scopes
            for point in trend_store.series(scope.scope_id)
        ]
        events = chronicle_events(
            config_events=config_events,
            discovery_rows=discovery_rows,
            change_rows=_change_rows_for(scopes, scope_id),
            incident_reports=incident_reports,
            prediction_reports=prediction_reports,
            compass_plans=plans,
            audit_events=unified_audit_events(cfg("ATLAS_WORKSPACE_ROOT")),
            policy_trend=trend_points,
        )
        filters = ChronicleFilter.from_args(request.args)
        sites, _platforms = _device_maps()
        filtered = filter_events(events, filters, sites_by_device=sites)
        page = paginate(filtered, filters.page, filters.per_page)
        activity = []
        for entry in page.items:
            shaped = dict(entry)
            shaped["when"] = format_with_relative(entry["occurred_at"], tz=tz)
            activity.append(shaped)

        return render_template(
            "timeline.html",
            activity=activity,
            page=page,
            filters=filters,
            filter_args=filters.to_args(),
            kind_counts=summarize_kinds(events),
            option_actors=sorted(
                {str(e.get("actor")) for e in events if e.get("actor")}
            ),
            option_sites=sorted(set(sites.values())),
            change_count=len(config_events),
            discovery_count=len(discovery_rows),
            totals=totals,
            evidence_totals=evidence_totals,
            **context,
        )

    @app.route("/audit")
    def audit_page():
        """The consolidated mutation audit: every operator change, one
        filterable view — site overrides and identity resolutions read
        through adapters (their undo semantics stay in their own files),
        everything newer straight from the unified log."""

        from founderos_atlas.audit import unified_audit_events
        from founderos_atlas.listing import int_arg, paginate

        context, _scopes, _scope_id = scoped_context("audit")
        category = request.args.get("category", "").strip()
        actor = request.args.get("actor", "").strip()
        subject = request.args.get("subject", "").strip()
        events = unified_audit_events(
            cfg("ATLAS_WORKSPACE_ROOT"),
            category=category or None,
            actor=actor or None,
            subject_contains=subject or None,
        )
        page = paginate(
            [event.to_dict() for event in events],
            int_arg(request.args, "page", 1, 100000),
            int_arg(request.args, "per_page", 50, 200),
        )
        all_events = unified_audit_events(cfg("ATLAS_WORKSPACE_ROOT"))
        return render_template(
            "audit.html",
            page=page,
            category=category,
            actor=actor,
            subject=subject,
            option_categories=sorted({e.category for e in all_events}),
            option_actors=sorted({e.actor for e in all_events}),
            **context,
        )

    @app.route("/audit/export.csv")
    def audit_export():
        import csv
        import io

        from founderos_atlas.audit import export_rows, unified_audit_events

        events = unified_audit_events(
            cfg("ATLAS_WORKSPACE_ROOT"),
            category=request.args.get("category", "").strip() or None,
            actor=request.args.get("actor", "").strip() or None,
            subject_contains=request.args.get("subject", "").strip() or None,
        )
        rows = export_rows(events)
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=list(rows[0].keys()) if rows else [
                "occurred_at", "actor", "scope", "category", "operation",
                "subject", "before", "after", "reason", "source",
                "correlation_id", "event_id",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
        return app.response_class(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit.csv"},
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
        query = (request.args.get("q") or "").strip().casefold()
        platform_filter = (request.args.get("platform") or "").strip()
        all_platforms = sorted({row["platform"] for row in devices if row["platform"] != "—"})
        if query:
            devices = [row for row in devices if query in " ".join(
                str(row.get(key) or "") for key in ("hostname", "device_id", "network", "platform")
            ).casefold()]
        if platform_filter:
            devices = [row for row in devices if row["platform"] == platform_filter]
        page = max(1, _page_arg())
        total_pages = max(1, -(-len(devices) // EVIDENCE_PAGE_SIZE))
        page = min(page, total_pages)
        visible_devices = devices[(page - 1) * EVIDENCE_PAGE_SIZE:page * EVIDENCE_PAGE_SIZE]
        events.sort(key=lambda item: item.occurred_at, reverse=True)
        # Sorting and day-keying use the stored UTC instants; only the
        # rendered strings are converted to the operator's zone.
        days = group_by_day(tuple(events[:60]), day_of=day_key_for(tz))
        for day in days:
            for event in day["events"]:
                event["occurred_at"] = format_timestamp(event["occurred_at"], tz=tz)
        return render_template(
            "configuration.html",
            devices=visible_devices,
            device_count=len(devices), page=page, total_pages=total_pages,
            platforms=all_platforms, platform_filter=platform_filter,
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
            config_query = (request.args.get("config_q") or "").strip()
            if config_query:
                needle = config_query.casefold()
                viewer["lines"] = [line for line in viewer["lines"]
                                   if needle in str(line.get("text") or "").casefold()]
                viewer["visible_line_count"] = len(viewer["lines"])
            else:
                viewer["visible_line_count"] = viewer["line_count"]
            for line in viewer["lines"]:
                stripped = str(line.get("text") or "").lstrip()
                line["syntax_class"] = (
                    "config-comment" if stripped.startswith(("!", "#")) else
                    "config-negation" if stripped.startswith("no ") else
                    "config-section" if stripped.startswith(("interface ", "router ", "line ", "vrf ")) else
                    "config-command"
                )
            viewer["truncated"] = len(viewer["lines"]) > EVIDENCE_MAX_VIEW_LINES
            viewer["lines"] = viewer["lines"][:EVIDENCE_MAX_VIEW_LINES]
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
            config_query=(request.args.get("config_q") or "").strip(),
            annotation=__import__("founderos_atlas.audit", fromlist=["AnnotationStore"]).AnnotationStore(
                cfg("ATLAS_WORKSPACE_ROOT")
            ).get("configuration-annotation", device_id),
            timeline=[
                _timeline_row(event)
                for event in device_timeline(history, config_text=store.config_text)
            ],
            **context,
        )

    @app.route("/evidence/bulk-export", methods=["POST"])
    def evidence_bulk_export():
        """Export selected devices as masked bundles; raw bulk export is forbidden."""
        from flask import Response
        import io
        import zipfile
        from founderos_atlas.web.evidence_bundle import build_device_bundle, safe_name
        _context, scopes, scope_id = scoped_context("memory")
        session_id = request.form.get("session", "").strip()
        device_ids = tuple(dict.fromkeys(request.form.getlist("device_ids")))[:200]
        service, _scope = _find_memory(scopes, scope_id, session_id=session_id)
        if service is None or not device_ids:
            flash("Select at least one device to export.", "error")
            return redirect(url_for("evidence_page", session=session_id))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for device_id in device_ids:
                bundle = build_device_bundle(service, device_id, raw=False, session_id=session_id)
                if bundle:
                    archive.writestr(f"{safe_name(device_id, fallback='device')}.zip", bundle)
            archive.writestr("REDACTION-NOTICE.txt", "All command output in this bulk export is masked.\n")
        return Response(output.getvalue(), content_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="atlas-evidence-selection-masked.zip"'
        })

    @app.route("/configuration/<path:device_id>/annotation", methods=["POST"])
    def configuration_annotation(device_id: str):
        from founderos_atlas.audit import AnnotationStore
        note = request.form.get("note", "").strip()
        if not note:
            flash("An annotation note is required.", "error")
        else:
            AnnotationStore(cfg("ATLAS_WORKSPACE_ROOT")).set(
                kind="configuration-annotation", subject=device_id,
                fields={"note": note, "status": request.form.get("status", "note")},
                reason=request.form.get("reason") or "Configuration annotation",
            )
            flash("Configuration annotation saved and audited.", "success")
        return redirect(url_for("configuration_device", device_id=device_id))

    @app.route("/configuration/<path:device_id>/export/<int:version>/redacted")
    def configuration_export_redacted(device_id: str, version: int):
        from flask import Response
        from founderos_atlas.config_memory import config_view
        _context, scopes, scope_id = scoped_context("configuration")
        store, history, _scope = _find_history(scopes, scope_id, device_id)
        if history is None:
            abort(404)
        raw = store.version_text(device_id, version)
        if raw is None:
            abort(404)
        masked = "\n".join(line["text"] for line in config_view(raw).to_dict()["lines"])
        return Response(masked, content_type="text/plain; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="configuration-v{version}-redacted.txt"'
        })

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
            for scope in with_data:
                refresh_scope_topology_viewer(scope)
            viewers = [
                {
                    "label": scope.label,
                    "scope_id": scope.scope_id,
                    "href": _current_topology_viewer_url(
                        f"/artifacts/{artifact_prefix(scope)}atlas_topology.html",
                        scope.output_dir / "atlas_topology.html",
                    ),
                }
                for scope in with_data
                if (scope.output_dir / "atlas_topology.html").is_file()
            ]
            if any(not scope.is_default for scope in with_data):
                # Enterprise federation (PR-037A): one canonical graph with
                # provenance, merge decisions, and visible boundaries.
                graph, snapshot = enterprise_world()
                if snapshot is not None:
                    _refresh_current_topology_viewer(
                        enterprise_scope_dir(output_dir()),
                        workspace_root=cfg("ATLAS_WORKSPACE_ROOT"),
                        last_discovered=snapshot.get("created_at"),
                    )
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
                facts = _topology_operational_facts(
                    enterprise_scope_dir(output_dir()),
                    workspace_root=cfg("ATLAS_WORKSPACE_ROOT"),
                    last_discovered=(
                        snapshot.get("created_at") if snapshot else None
                    ),
                )
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
                    facts=facts,
                    topology_src=_current_topology_viewer_url(
                        f"/artifacts/{ENTERPRISE_ARTIFACT_PREFIX}atlas_topology.html",
                        enterprise_scope_dir(output_dir()) / "atlas_topology.html",
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
        refresh_scope_topology_viewer(scope)
        exists = (scope.output_dir / "atlas_topology.html").is_file()
        return render_template(
            "topology.html",
            global_view=False,
            has_topology=exists,
            facts=_topology_operational_facts(
                scope.output_dir,
                workspace_root=cfg("ATLAS_WORKSPACE_ROOT"),
            ),
            topology_src=_current_topology_viewer_url(
                f"/artifacts/{artifact_prefix(scope)}atlas_topology.html",
                scope.output_dir / "atlas_topology.html",
            ),
            **context,
        )

    @app.route("/api/topology/counts")
    def api_topology_counts():
        """The canonical topology counts and their definitions, per scope."""

        context, scopes, scope_id = scoped_context("topology")
        if scope_id == GLOBAL_SCOPE_ID:
            target = enterprise_scope_dir(output_dir())
            enterprise_world()  # ensure the federated snapshot exists
        else:
            target = scopes[scope_id].output_dir
        facts = _topology_operational_facts(
            target, workspace_root=cfg("ATLAS_WORKSPACE_ROOT")
        )
        if facts is None:
            return jsonify({
                "scope": scope_id, "counts": None,
                "detail": "no topology snapshot exists for this scope",
            })
        return jsonify({
            "scope": scope_id,
            "counts": facts["counts"],
            "definitions": facts["definitions"],
            "observed_at": facts["observed_at"],
        })

    @app.route("/api/health")
    def api_health():
        """The canonical health assessment for the requested scope."""

        from founderos_atlas.health import aggregate_assessments

        context, scopes, scope_id = scoped_context("dashboard")
        if scope_id == GLOBAL_SCOPE_ID:
            aggregated = aggregation_scopes(scopes)
            assessment = aggregate_assessments(
                [
                    health_for(scope, summary_for(scope))
                    for scope in aggregated
                ],
                scope_id=GLOBAL_SCOPE_ID,
                scope_label=GLOBAL_SCOPE_LABEL,
                generated_at=now_iso(),
            )
        else:
            scope = scopes[scope_id]
            assessment = health_for(scope, summary_for(scope))
        return jsonify(assessment.to_dict())

    def refresh_curated_topologies() -> None:
        """Re-render current artifacts only; immutable history stays frozen."""

        scopes = known_scopes()
        for scope in aggregation_scopes(scopes):
            if scope.snapshot_path.is_file():
                refresh_scope_topology_viewer(scope, force=True)
        # Workspace JSON participates in the enterprise fingerprint, but
        # explicitly clear the in-process cache so the mutation response has
        # already rebuilt the artifact before the iframe reloads.
        enterprise_cache.update(fingerprint=None, graph=None, snapshot=None)
        if any(
            scope.snapshot_path.is_file()
            for scope in aggregation_scopes(scopes)
        ):
            enterprise_world()

    def curation_payload() -> dict:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="A JSON object is required.")
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            abort(403, description="Cross-origin topology edits are refused.")
        return payload

    def override_identity(payload: dict) -> dict:
        return {
            "device_id": str(payload.get("device_id") or "").strip() or None,
            "hostname": str(payload.get("hostname") or "").strip() or None,
            "management_ip": (
                str(payload.get("management_ip") or "").strip() or None
            ),
            "serial_number": (
                str(payload.get("serial_number") or "").strip() or None
            ),
            "vendor": str(payload.get("vendor") or "").strip() or None,
        }

    @app.route("/api/topology/curation")
    def api_topology_curation():
        workspace = cfg("ATLAS_WORKSPACE_ROOT")
        catalog = SiteCatalogRepository(workspace).load()
        repository = SiteOverrideRepository(workspace)
        overrides = repository.load()
        return jsonify({
            "catalog": catalog.to_dict(),
            "overrides": overrides.to_dict(),
            "history": [item.to_dict() for item in repository.history()],
            "operator": current_actor(),
            "authorization": (
                f"server-side topology edit permission; authentication mode "
                f"{app.config.get('ATLAS_AUTH_MODE', 'local')}"
            ),
        })

    @app.route("/api/topology/site-assignments", methods=["PUT"])
    def api_assign_topology_site():
        payload = curation_payload()
        site_id = str(payload.get("site_id") or "").strip()
        catalog = SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load()
        if site_id != "__none__" and catalog.get(site_id) is None:
            return jsonify(error="The requested site does not exist."), 400
        expected = payload.get("expected_revision")
        try:
            result, event = SiteOverrideRepository(
                cfg("ATLAS_WORKSPACE_ROOT")
            ).assign(
                site_id=site_id,
                reason=str(payload.get("reason") or "").strip() or None,
                actor=current_actor(),
                expected_revision=int(expected) if expected is not None else None,
                **override_identity(payload),
            )
        except SiteOverrideConflictError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        refresh_curated_topologies()
        return jsonify(
            revision=result.revision,
            event=event.to_dict(),
            message="Persistent site assignment saved.",
        )

    @app.route("/api/topology/site-assignments/revert", methods=["POST"])
    def api_revert_topology_site():
        payload = curation_payload()
        expected = payload.get("expected_revision")
        try:
            result, event = SiteOverrideRepository(
                cfg("ATLAS_WORKSPACE_ROOT")
            ).revert(
                reason=str(payload.get("reason") or "").strip() or None,
                actor=current_actor(),
                expected_revision=int(expected) if expected is not None else None,
                **override_identity(payload),
            )
        except SiteOverrideConflictError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        refresh_curated_topologies()
        return jsonify(
            revision=result.revision,
            event=event.to_dict(),
            message="Returned to evidence-based site inference.",
        )

    @app.route("/api/topology/site-assignments/undo", methods=["POST"])
    def api_undo_topology_site():
        payload = curation_payload()
        subject_key = str(payload.get("subject_key") or "").strip()
        if not subject_key:
            return jsonify(error="subject_key is required."), 400
        expected = payload.get("expected_revision")
        try:
            result, event = SiteOverrideRepository(
                cfg("ATLAS_WORKSPACE_ROOT")
            ).undo(
                subject_key=subject_key,
                actor=current_actor(),
                expected_revision=int(expected) if expected is not None else None,
            )
        except SiteOverrideConflictError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        refresh_curated_topologies()
        return jsonify(
            revision=result.revision,
            event=event.to_dict(),
            message="Last site assignment change undone.",
        )

    # -- Peer identity resolution (operator workflow) ----------------------
    #
    # Same contract as site curation: durable, audited, revision-checked,
    # undoable. Atlas suggests candidates with evidence; only the operator
    # merges. The form endpoints keep the workflow fully usable without
    # JavaScript; the JSON API mirrors them for the viewer.

    def _resolution_repo() -> PeerResolutionRepository:
        return PeerResolutionRepository(cfg("ATLAS_WORKSPACE_ROOT"))

    def _expected_revision(raw) -> int | None:
        text = str(raw or "").strip()
        return int(text) if text else None

    @app.route("/topology/identity/resolve", methods=["POST"])
    def topology_identity_resolve():
        try:
            _, event = _resolution_repo().resolve(
                actor=current_actor(),
                peer_label=str(request.form.get("peer_label") or ""),
                resolved_hostname=str(
                    request.form.get("resolved_hostname") or ""
                ),
                reason=str(request.form.get("reason") or "").strip() or None,
                expected_revision=_expected_revision(
                    request.form.get("expected_revision")
                ),
            )
        except PeerResolutionConflictError as error:
            flash(str(error), "error")
        except ValueError as error:
            flash(str(error), "error")
        else:
            refresh_curated_topologies()
            flash(
                f"Resolved {event.peer_label} to {event.after_hostname}. "
                "Every future view applies this decision until reverted.",
                "success",
            )
        return redirect("/topology#identity")

    @app.route("/topology/identity/revert", methods=["POST"])
    def topology_identity_revert():
        try:
            _, event = _resolution_repo().revert(
                actor=current_actor(),
                peer_label=str(request.form.get("peer_label") or ""),
                reason=str(request.form.get("reason") or "").strip() or None,
                expected_revision=_expected_revision(
                    request.form.get("expected_revision")
                ),
            )
        except (PeerResolutionConflictError, ValueError) as error:
            flash(str(error), "error")
        else:
            refresh_curated_topologies()
            flash(
                f"{event.peer_label} is unresolved again — the audit trail "
                "keeps the full history.",
                "success",
            )
        return redirect("/topology#identity")

    @app.route("/topology/identity/undo", methods=["POST"])
    def topology_identity_undo():
        try:
            _, event = _resolution_repo().undo(
                actor=current_actor(),
                subject_key=str(request.form.get("subject_key") or ""),
            )
        except (PeerResolutionConflictError, ValueError) as error:
            flash(str(error), "error")
        else:
            refresh_curated_topologies()
            flash(
                f"Undid {event.undoes_event_id} for {event.peer_label}.",
                "success",
            )
        return redirect("/topology#identity")

    @app.route("/api/topology/identity-resolutions", methods=["PUT"])
    def api_resolve_peer_identity():
        payload = curation_payload()
        try:
            result, event = _resolution_repo().resolve(
                actor=current_actor(),
                peer_label=str(payload.get("peer_label") or ""),
                resolved_hostname=str(payload.get("resolved_hostname") or ""),
                resolved_device_id=(
                    str(payload.get("resolved_device_id") or "").strip() or None
                ),
                reason=str(payload.get("reason") or "").strip() or None,
                expected_revision=_expected_revision(
                    payload.get("expected_revision")
                ),
            )
        except PeerResolutionConflictError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        refresh_curated_topologies()
        return jsonify(
            revision=result.revision,
            event=event.to_dict(),
            message="Peer identity resolution saved.",
        )

    @app.route("/api/topology/identity-resolutions/revert", methods=["POST"])
    def api_revert_peer_identity():
        payload = curation_payload()
        try:
            result, event = _resolution_repo().revert(
                actor=current_actor(),
                peer_label=str(payload.get("peer_label") or ""),
                reason=str(payload.get("reason") or "").strip() or None,
                expected_revision=_expected_revision(
                    payload.get("expected_revision")
                ),
            )
        except PeerResolutionConflictError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        refresh_curated_topologies()
        return jsonify(
            revision=result.revision,
            event=event.to_dict(),
            message="The peer is unresolved again.",
        )

    @app.route("/api/topology/identity-resolutions/undo", methods=["POST"])
    def api_undo_peer_identity():
        payload = curation_payload()
        try:
            result, event = _resolution_repo().undo(
                actor=current_actor(),
                subject_key=str(payload.get("subject_key") or ""),
            )
        except PeerResolutionConflictError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        refresh_curated_topologies()
        return jsonify(
            revision=result.revision,
            event=event.to_dict(),
            message="Last identity resolution change undone.",
        )

    @app.route("/api/topology/sites/<site_id>", methods=["PUT"])
    def api_update_topology_site(site_id: str):
        from dataclasses import replace

        payload = curation_payload()
        site_type = str(payload.get("site_type") or "").strip()
        if site_type not in SITE_TYPES:
            return jsonify(
                error="site_type must be one of " + ", ".join(SITE_TYPES)
            ), 400
        repository = SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        catalog = repository.load()
        existing = catalog.get(site_id)
        if existing is None:
            return jsonify(error="The requested site does not exist."), 404
        repository.save(SiteCatalog(sites=tuple(
            replace(site, site_type=site_type)
            if site.site_id == site_id else site
            for site in catalog.sites
        )))
        refresh_curated_topologies()
        return jsonify(
            site_id=site_id,
            site_type=site_type,
            message="Site type saved.",
        )

    def _find_history_run(scopes, scope_id, record_id: str):
        """One discovery run by id, searched in the visible scopes.

        Returns ``(record_dict, scope)`` or ``(None, None)`` — an unknown
        run renders an honest not-found note, never a 500."""

        candidates = (
            aggregation_scopes(scopes)
            if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],)
        )
        for scope in candidates:
            repo = HistoryRepository(scope.history_root)
            index = repo.load()
            for position, record in enumerate(index.records):
                if record.record_id != record_id:
                    continue
                from .timefmt import format_timestamp

                run = record.to_dict()
                run["scope_label"] = scope.label
                run["scope_id"] = scope.scope_id
                run["started_display"] = format_timestamp(
                    record.started_at, tz=display_timezone()
                )
                run["profile"] = record.profile_name or scope.label

                # Explicit run state, derived honestly from what the
                # record proves — never a guess at what a scheduler meant.
                if record.device_count == 0 and record.failures:
                    run["state"] = "failed"
                elif record.failures:
                    run["state"] = "partial"
                elif record.network_status.casefold() == "interrupted":
                    run["state"] = "interrupted"
                else:
                    run["state"] = "completed"

                # Evidence coverage: configurations held over devices seen.
                run["evidence_coverage"] = {
                    "numerator": record.configured_device_count,
                    "denominator": record.device_count,
                    "status": record.configuration_status,
                }

                # Collection failures within this run's evidence session,
                # when the memory holds one under this record id; absence
                # is stated, not invented.
                collection = {"available": False, "failed": 0, "empty": 0,
                              "collected": 0}
                try:
                    for evidence in memory_store(scope).evidence_records(
                        discovery_session=record.record_id
                    ):
                        collection["available"] = True
                        status = str(evidence.collection_status or "")
                        if status == "ok":
                            collection["collected"] += 1
                        elif status == "empty":
                            collection["empty"] += 1
                        else:
                            collection["failed"] += 1
                except Exception:  # noqa: BLE001 - memory is optional
                    pass
                run["collection"] = collection

                # Changes against the PREVIOUS run of the same scope: count
                # plus the compare deep link (records are newest-first).
                previous = (
                    index.records[position + 1]
                    if position + 1 < len(index.records) else None
                )
                run["previous_record_id"] = (
                    previous.record_id if previous else None
                )
                if previous is not None:
                    try:
                        from founderos_atlas.change import ChangeDetector

                        left = load_json(
                            repo.snapshot_path(previous.record_id)
                        )
                        right = load_json(repo.snapshot_path(record.record_id))
                        if left is not None and right is not None:
                            run["changes_detected"] = ChangeDetector().compare(
                                left, right
                            ).change_count
                    except Exception:  # noqa: BLE001 - diff is best-effort
                        run["changes_detected"] = None
                return run, scope
        return None, None

    @app.route("/history")
    def history():
        context, scopes, scope_id = scoped_context("history")
        # Deep link: ?run=<record_id> opens one discovery run's detail —
        # the stable address every "Open discovery" link points at.
        run = None
        requested_run = request.args.get("run", "").strip()
        if requested_run:
            run, _run_scope = _find_history_run(scopes, scope_id, requested_run)
            if run is None:
                flash(
                    f"No discovery run '{requested_run}' exists in this "
                    "scope — it may belong to another scope or have been "
                    "removed.",
                    "warning",
                )
        if scope_id == GLOBAL_SCOPE_ID:
            records, issues = merged_history_rows(aggregation_scopes(scopes))
            return render_template(
                "history.html",
                records=records,
                issues=issues,
                show_profile=True,
                run=run,
                **context,
            )
        scope = scopes[scope_id]
        index = HistoryRepository(scope.history_root).load()
        return render_template(
            "history.html",
            records=history_rows(index, scope_label=scope.label),
            issues=index.issues,
            show_profile=False,
            run=run,
            **context,
        )

    def _change_rows_for(scopes, scope_id):
        """Unified, annotated change rows across the visible scope(s)."""

        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.change.explorer import annotate_rows, unified_rows

        candidates = (
            aggregation_scopes(scopes)
            if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],)
        )
        rows: list[dict] = []
        for scope in candidates:
            out = scope.output_dir
            incident = load_json(out / "incident_report.json") or {}
            rows.extend(unified_rows(
                topology_report=load_json(out / "change_report.json"),
                config_report=load_json(out / "config_change_report.json"),
                state_report=load_json(out / "state_change_report.json"),
                network=scope.label,
                incident_devices=frozenset(
                    str(name) for name in incident.get("affected_devices") or ()
                ),
            ))
        store = AnnotationStore(cfg("ATLAS_WORKSPACE_ROOT"))
        return annotate_rows(
            rows,
            acks=store.all("change-ack"),
            assignments=store.all("change-assignment"),
            notes=store.all("change-note"),
            suppressions=store.all("change-suppression"),
        )

    @app.route("/changes")
    def changes():
        """Change Intelligence as an investigation (PR-053): one filtered,
        paginated row model over the topology, configuration, and
        operational change reports — with before/after, acknowledgement,
        ownership, notes, suppression, incident correlation, export, and
        run-to-run comparison. Filters live in the URL."""

        from founderos_atlas.change.explorer import (
            ChangeFilter,
            filter_rows,
            summarize,
        )
        from founderos_atlas.listing import paginate

        context, scopes, scope_id = scoped_context("changes")
        rows = _change_rows_for(scopes, scope_id)
        filters = ChangeFilter.from_args(request.args)
        filtered, hidden_suppressed = filter_rows(rows, filters)
        page = paginate(filtered, filters.page, filters.per_page)
        run_options = []
        for scope in (
            aggregation_scopes(scopes)
            if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],)
        ):
            index = HistoryRepository(scope.history_root).load()
            for record in index.records[:20]:
                run_options.append({
                    "record_id": record.record_id,
                    "label": (
                        f"{record.profile_name or scope.label} · "
                        f"{record.started_at}"
                    ),
                    "scope_id": scope.scope_id,
                })
        return render_template(
            "changes.html",
            filters=filters,
            filter_args=filters.to_args(),
            page=page,
            summary=summarize(rows),
            hidden_suppressed=hidden_suppressed,
            option_kinds=sorted({str(r.get("kind")) for r in rows}),
            option_categories=sorted({str(r.get("category")) for r in rows}),
            option_severities=sorted({str(r.get("severity")) for r in rows}),
            run_options=run_options,
            comparison=None,
            **context,
        )

    @app.route("/changes/compare")
    def changes_compare():
        """Any two archived discovery runs, diffed on demand — the change
        reports cover consecutive runs; this covers ANY pair."""

        from founderos_atlas.change import ChangeDetector
        from founderos_atlas.change.explorer import (
            ChangeFilter,
            annotate_rows,
            filter_rows,
            summarize,
            unified_rows,
        )
        from founderos_atlas.listing import paginate

        context, scopes, scope_id = scoped_context("changes")
        left_id = request.args.get("left", "").strip()
        right_id = request.args.get("right", "").strip()
        comparison = None
        rows: list[dict] = []
        if left_id and right_id:
            left_snapshot = right_snapshot = None
            left_scope_label = ""
            for scope in (
                aggregation_scopes(scopes)
                if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],)
            ):
                repo = HistoryRepository(scope.history_root)
                left_path = repo.snapshot_path(left_id)
                if left_path.is_file():
                    left_snapshot = load_json(left_path)
                    left_scope_label = scope.label
                right_path = repo.snapshot_path(right_id)
                if right_path.is_file():
                    right_snapshot = load_json(right_path)
            if left_snapshot is None or right_snapshot is None:
                flash(
                    "One or both runs could not be found in this scope — "
                    "they may belong to another scope or have been removed.",
                    "warning",
                )
            else:
                report = ChangeDetector().compare(left_snapshot, right_snapshot)
                rows = annotate_rows(unified_rows(
                    topology_report=report.to_dict(),
                    config_report=None,
                    state_report=None,
                    network=left_scope_label,
                ))
                comparison = {"left": left_id, "right": right_id,
                              "count": len(rows)}
        filters = ChangeFilter.from_args(request.args)
        filtered, hidden_suppressed = filter_rows(rows, filters)
        page = paginate(filtered, filters.page, filters.per_page)
        run_options = []
        for scope in (
            aggregation_scopes(scopes)
            if scope_id == GLOBAL_SCOPE_ID else (scopes[scope_id],)
        ):
            index = HistoryRepository(scope.history_root).load()
            for record in index.records[:20]:
                run_options.append({
                    "record_id": record.record_id,
                    "label": (
                        f"{record.profile_name or scope.label} · "
                        f"{record.started_at}"
                    ),
                    "scope_id": scope.scope_id,
                })
        return render_template(
            "changes.html",
            filters=filters,
            filter_args=filters.to_args(),
            page=page,
            summary=summarize(rows),
            hidden_suppressed=hidden_suppressed,
            option_kinds=sorted({str(r.get("kind")) for r in rows}),
            option_categories=sorted({str(r.get("category")) for r in rows}),
            option_severities=sorted({str(r.get("severity")) for r in rows}),
            run_options=run_options,
            comparison=comparison,
            **context,
        )

    @app.route("/changes/export.csv")
    def changes_export():
        import csv
        import io

        from founderos_atlas.change.explorer import (
            ChangeFilter,
            export_rows,
            filter_rows,
        )

        context, scopes, scope_id = scoped_context("changes")
        rows = _change_rows_for(scopes, scope_id)
        filters = ChangeFilter.from_args(request.args)
        filtered, _hidden = filter_rows(rows, filters)
        exported = export_rows(filtered)
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=list(exported[0].keys()) if exported else [
                "kind", "category", "severity", "device", "field", "before",
                "after", "description", "recommendation", "network",
                "occurred_at", "acknowledged", "owner", "suppressed",
                "subject",
            ],
        )
        writer.writeheader()
        writer.writerows(exported)
        return app.response_class(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=changes.csv"},
        )

    @app.route("/changes/annotate", methods=["POST"])
    def changes_annotate():
        """Acknowledge, assign, note, or suppress one change — audited."""

        from founderos_atlas.audit import AnnotationStore

        action = str(request.form.get("action") or "").strip()
        subject = str(request.form.get("subject") or "").strip()
        if not subject or action not in (
            "acknowledge", "unacknowledge", "assign", "note", "suppress",
            "unsuppress",
        ):
            flash("Unknown change action.", "error")
            return redirect(safe_redirect_target(
                request.form.get("next"), scoped_url("/changes")
            ))
        store = AnnotationStore(cfg("ATLAS_WORKSPACE_ROOT"))
        reason = str(request.form.get("reason") or "").strip() or None
        try:
            if action == "acknowledge":
                store.set(actor=current_actor(), kind="change-ack", subject=subject,
                          fields={"acknowledged": True}, reason=reason,
                          occurred_at=now_iso())
                flash("Change acknowledged (audited).", "success")
            elif action == "unacknowledge":
                store.clear(actor=current_actor(), kind="change-ack", subject=subject,
                            reason=reason, occurred_at=now_iso())
                flash("Acknowledgement removed (audited).", "success")
            elif action == "assign":
                owner = str(request.form.get("owner") or "").strip()
                if not owner:
                    raise ValueError("an assignment needs an owner")
                from founderos_atlas.notifications import (
                    KIND_ASSIGNMENT, NotificationStore,
                )

                # Identify the change so the recipient never lands on the
                # generic page wondering which row was meant: resolve the
                # row server-side and link to it, device-filtered with the
                # row's own anchor.
                scope_id = _scope_from_next(request.form.get("next"))
                change_row = next(
                    (
                        row
                        for row in _change_rows_for(known_scopes(), scope_id)
                        if str(row.get("subject") or "") == subject
                    ),
                    None,
                )
                previous_owner = str(
                    (store.get("change-assignment", subject) or {}).get(
                        "owner"
                    ) or ""
                )
                if change_row is not None:
                    device = str(change_row.get("device") or "unknown")
                    what = str(
                        change_row.get("description")
                        or change_row.get("category") or "change"
                    )[:80]
                    title = f"Change assigned: {what} on {device}"
                    severity = str(change_row.get("severity") or "unknown")
                    detail = (
                        f"{severity.capitalize()} severity · "
                        f"{str(change_row.get('network') or 'Enterprise')} · "
                        f"Assigned by {current_actor()}."
                    )
                    href = (
                        scoped_url("/changes", scope_id, device=device)
                        + f"#{subject}"
                    )
                else:
                    title = "A change was assigned to you"
                    detail = f"Assigned by {current_actor()}."
                    href = safe_redirect_target(
                        request.form.get("next"), "/changes"
                    )
                if previous_owner != owner:
                    # Same owner re-assigned: audited, but not a new event
                    # for the recipient — no duplicate unread notification.
                    NotificationStore(cfg("ATLAS_WORKSPACE_ROOT")).notify(
                        kind=KIND_ASSIGNMENT,
                        title=title,
                        detail=detail,
                        href=href,
                        audience=owner,
                    )
                store.set(actor=current_actor(), kind="change-assignment", subject=subject,
                          fields={"owner": owner}, reason=reason,
                          occurred_at=now_iso())
                flash(f"Change assigned to {owner} (audited).", "success")
            elif action == "note":
                note = str(request.form.get("note") or "").strip()
                if not note:
                    raise ValueError("a note needs text")
                store.set(actor=current_actor(), kind="change-note", subject=subject,
                          fields={"note": note}, occurred_at=now_iso())
                flash("Note attached (audited).", "success")
            elif action == "suppress":
                if not reason:
                    raise ValueError("suppressing a change requires a reason")
                store.set(actor=current_actor(), kind="change-suppression", subject=subject,
                          fields={"reason": reason}, reason=reason,
                          occurred_at=now_iso())
                flash(
                    "Change suppressed — hidden by default, always countable, "
                    "and audited.",
                    "success",
                )
            elif action == "unsuppress":
                store.clear(actor=current_actor(), kind="change-suppression", subject=subject,
                            reason=reason, occurred_at=now_iso())
                flash("Suppression removed (audited).", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(safe_redirect_target(
            request.form.get("next"), scoped_url("/changes")
        ))

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
                scenarios=(load_json(
                    enterprise_scope_dir(output_dir())
                    / "prediction_scenarios.json"
                ) or [])[:8],
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
            scenarios=(load_json(
                scopes[scope_id].output_dir / "prediction_scenarios.json"
            ) or [])[:8],
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
        change_type = request.form.get("change_type", "shutdown-interface").strip()
        # Only engine-modeled types are offered; anything else falls back
        # to the modeled default rather than pretending.
        if change_type not in ("shutdown-interface", "reboot-device"):
            change_type = "shutdown-interface"
        needs_interface = change_type == "shutdown-interface"
        if not device or (needs_interface and not interface):
            flash(
                "A device is required"
                + (" and an interface for interface changes" if needs_interface
                   else "")
                + ".",
                "error",
            )
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
        if needs_interface:
            device, interface, problem = validated_change_target(
                snapshot, device, interface, scope_label
            )
        else:
            interface = None
            known = {
                str(entry.get("hostname") or "").casefold()
                for entry in (snapshot or {}).get("devices") or ()
                if isinstance(entry, dict)
            }
            problem = (
                None if device.casefold() in known else
                f"{device} is not in {scope_label}'s latest discovery."
            )
        if problem is not None:
            flash(problem, "error")
            return redirect(url_for("predict_page"))
        generated_at = now_iso()
        change = ChangeRequest(
            request_id=f"gui-{device}-{interface or change_type}".replace(" ", "-"),
            change_type=change_type,
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
        # Saved scenario: the prediction's own facts, replayable and
        # comparable, addable to Compass.
        scenario = {
            "scenario_id": f"scn-{uuid4().hex[:8]}",
            "generated_at": generated_at,
            "scope_id": scope_id,
            "change_type": change_type,
            "device": device,
            "interface": interface,
            "risk": (prediction.to_dict().get("risk") or {}).get("level"),
            "confidence": (
                prediction.to_dict().get("confidence") or {}
            ).get("percent"),
            "summary": (
                prediction.to_dict().get("blast_radius") or {}
            ).get("summary"),
        }
        scenarios_path = out_dir / "prediction_scenarios.json"
        existing_scenarios = load_json(scenarios_path) or []
        if not isinstance(existing_scenarios, list):
            existing_scenarios = []
        existing_scenarios.insert(0, scenario)
        scenarios_path.write_text(
            __import__("json").dumps(existing_scenarios[:20], indent=2)
            + "\n",
            encoding="utf-8",
        )
        case_id = request.form.get("case_id", "").strip()
        if case_id:
            from founderos_atlas.incidents.records import (
                IncidentCaseRepository,
            )

            try:
                IncidentCaseRepository(cfg("ATLAS_WORKSPACE_ROOT")).link(
                    case_id, kind="prediction",
                    value=f"{change_type} {device} {interface or ''}".strip(),
                    actor=current_actor(),
                )
            except ValueError:
                pass
        flash("Prediction generated and scenario saved.", "success")
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

    def _intent_note(stored):
        """The honesty note that rides with a declared intent — it says
        exactly how much ACL evidence the verdict rests on, from the
        engine's own policy accounting (packet trace Phase 2)."""

        policy = (stored.get("basis") or {}).get("policy") or {}
        evaluated = int(policy.get("hops_evaluated") or 0)
        unevaluated = policy.get("hops_unevaluated") or []
        if evaluated and not unevaluated:
            return (
                "Declared intent, recorded with the investigation. ACL "
                "rules from the captured configurations were evaluated "
                f"against this packet at every hop ({evaluated}); "
                "qualifiers Atlas cannot decide from declared intent are "
                "reported per hop, never guessed."
            )
        if evaluated:
            return (
                "Declared intent, recorded with the investigation. ACL "
                f"rules were evaluated at {evaluated} hop(s); "
                f"{len(unevaluated)} hop(s) have no captured "
                "configuration and their policy is NOT evaluated — "
                "listed under what Atlas cannot see."
            )
        return (
            "Declared intent, recorded with the investigation. "
            "Atlas evaluated topology and device state; ACL and "
            "firewall policy for this protocol/port were NOT "
            "evaluated and are listed under what Atlas cannot see."
        )

    def _run_path_trace(source, destination, intent, case_id=""):
        """Run one deterministic path investigation for the active scope
        and return the stored report dict (with declared intent attached)
        or an error string. Shared by the Paths form and the topology
        viewer's packet-trace API — one engine, one record, one honesty
        note about how much policy evidence the verdict rests on."""

        from founderos_atlas.path_intelligence import (
            investigate_path_for_scope,
        )

        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        generated_at = now_iso()
        if scope_id == GLOBAL_SCOPE_ID:
            graph, snapshot = enterprise_world()
            if snapshot is None:
                return None, "No discovery has run yet in any network."
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
                intent=intent or None,
                policy_roots=tuple(
                    profile_scope(
                        output_dir(), profile.profile_id, profile.name
                    ).output_dir
                    for profile in profiles
                ),
            )
            report_dir = enterprise_dir
        else:
            scope = scopes[scope_id]
            investigate_path_for_scope(
                source,
                destination,
                output_dir=scope.output_dir,
                history_root=scope.history_root,
                generated_at=generated_at,
                profile_id=scope.scope_id,
                intent=intent or None,
            )
            report_dir = scope.output_dir
        report_path = report_dir / "path_investigation_report.json"
        stored = load_json(report_path)
        if not isinstance(stored, dict):
            return None, "The investigation produced no readable report."
        if intent:
            stored["intent"] = intent
            stored["intent_note"] = _intent_note(stored)
        if case_id:
            stored["case_id"] = case_id
            from founderos_atlas.incidents.records import (
                IncidentCaseRepository,
            )

            try:
                IncidentCaseRepository(cfg("ATLAS_WORKSPACE_ROOT")).link(
                    case_id, kind="path",
                    value=f"{source} → {destination}",
                    actor=current_actor(),
                )
            except ValueError:
                pass
        if intent or case_id:
            import json as _json

            report_path.write_text(
                _json.dumps(stored, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return stored, None

    @app.route("/paths/run", methods=["POST"])
    def paths_run():
        source = request.form.get("source", "").strip()
        destination = request.form.get("destination", "").strip()
        if not source or not destination:
            flash("A source and a destination device are required.", "error")
            return redirect(url_for("paths_page"))
        # Declared L3/L4 intent rides with the investigation as context.
        intent = {
            "vrf": request.form.get("vrf", "").strip(),
            "source_address": request.form.get("source_address", "").strip(),
            "protocol": request.form.get("protocol", "").strip(),
            "port": request.form.get("port", "").strip(),
        }
        intent = {key: value for key, value in intent.items() if value}
        _stored, error = _run_path_trace(
            source, destination, intent,
            case_id=request.form.get("case_id", "").strip(),
        )
        if error:
            flash(error, "error")
            return redirect(url_for("paths_page"))
        flash("Path investigation complete.", "success")
        return redirect(url_for("paths_page"))

    @app.route("/api/paths/trace", methods=["POST"])
    def api_paths_trace():
        """The topology viewer's packet trace: same engine, same stored
        record as the Paths page, returned as JSON for the animation.
        The hops carry per-hop status (pass/warning/failed/unknown) and
        the animation stops exactly where the engine did."""

        body = request.get_json(silent=True) or {}
        source = str(body.get("source") or "").strip()
        destination = str(body.get("destination") or "").strip()
        if not source or not destination:
            return {"error": "source and destination are required"}, 400
        protocol = str(body.get("protocol") or "").strip().lower()
        if protocol and protocol not in ("tcp", "udp", "icmp"):
            return {"error": "protocol must be tcp, udp, or icmp"}, 400
        port_raw = body.get("port")
        port = None
        if port_raw not in (None, ""):
            try:
                port = int(port_raw)
            except (TypeError, ValueError):
                return {"error": "port must be a number"}, 400
            if not 1 <= port <= 65535:
                return {"error": "port must be between 1 and 65535"}, 400
            if protocol == "icmp":
                return {"error": "icmp has no port — leave it blank"}, 400
        intent = {"protocol": protocol} if protocol else {}
        if port is not None:
            intent["port"] = str(port)
        stored, error = _run_path_trace(source, destination, intent)
        if error:
            return {"error": error}, 409
        return stored

    def _reachability_detail(state, hostname, probe_protocol):
        """What the protocol-correct probe settled, and what it did not."""

        if state == "reachable":
            return (
                f"{hostname} answered an ICMP probe, so the path carries "
                f"traffic to it — the traceroute's {probe_protocol.upper()} "
                "probes were filtered somewhere along the way, which is "
                "about those probes, not about your traffic."
            )
        if state == "unreachable":
            return (
                f"{hostname} did not answer an ICMP probe either, so the "
                "silence is not only about the traceroute's "
                f"{probe_protocol.upper()} probes."
            )
        return (
            f"The ICMP probe to {hostname} gave no verdict Atlas can read."
        )

    def _service_detail(state, port, hostname, evidence):
        """Say what the connect attempt proved — and what it did not.

        The distinction that matters to an engineer: a refusal proves
        the network delivered and the host answered, so a still-broken
        application is not a routing problem.
        """

        if state == "open":
            return (
                f"{hostname} accepted a TCP connection on port {port} — "
                "the path delivers and the service is listening."
            )
        if state == "refused":
            return (
                f"{hostname} actively refused port {port}. The network "
                "delivered the packet and the host answered, so this is "
                "the service, not the path — nothing is listening there."
            )
        if state == "no-answer":
            return (
                f"Nothing answered on port {port}. Atlas cannot tell a "
                "silent drop from a filter or a dead service apart from "
                "this evidence alone."
            )
        return (
            f"The connect attempt to port {port} gave no verdict Atlas "
            f"can read: {evidence}"
        )

    def _probe_verdict(actual, expected, predicted_path, dst, target_address):
        """Three-valued agreement between observed and predicted path.

        Matched as a SUBSEQUENCE, not position by position: only
        devices that decrement TTL answer a traceroute, so an L2
        switch (or a transparent firewall) on the predicted path is
        invisible to the probe and its absence is not disagreement.
        What would be disagreement is a device answering that the
        prediction never routed through, or predicted devices
        answering out of order. Silent hops and addresses Atlas cannot
        name prove nothing either way — they can make the verdict
        inconclusive, never confirmed."""

        destination_names = {dst.hostname.casefold()}
        skipped: list[str] = []
        position = -1
        for entry in actual:
            if not entry["address"] or not entry["device"]:
                continue
            name = entry["device"].casefold()
            try:
                found = expected.index(name, position + 1)
            except ValueError:
                if name in expected:
                    return "diverged", (
                        f"Hop {entry['index']} answered from "
                        f"{entry['address']} ({entry['device']}), which "
                        "the prediction routes through earlier — the "
                        "live path visits it out of order."
                    )
                return "diverged", (
                    f"Hop {entry['index']} answered from "
                    f"{entry['address']} ({entry['device']}), a device "
                    "the predicted path never routes through."
                )
            # Predicted devices between the last match and this one did
            # not answer: normal for anything that does not decrement
            # TTL, and worth naming rather than silently accepting.
            skipped.extend(predicted_path[i + 1] for i in range(position + 1, found))
            position = found
        reached = any(
            (entry["device"] or "").casefold() in destination_names
            or entry["address"] in (target_address, dst.management_ip)
            for entry in actual
        )
        silent = [e["index"] for e in actual if not e["address"]]
        unresolved = [
            e["address"] for e in actual if e["address"] and not e["device"]
        ]
        if reached and not silent and not unresolved:
            note = (
                " " + ", ".join(sorted(set(skipped)))
                + " did not answer (devices that do not decrement TTL, "
                "such as L2 switches, never appear in a traceroute)."
                if skipped else ""
            )
            return "confirmed", (
                "Every replying hop matches the predicted path and the "
                f"probe reached {dst.hostname}.{note}"
            )
        parts = []
        if not reached:
            parts.append(f"the probe never observed {dst.hostname} answering")
        if silent:
            parts.append(
                "hop(s) " + ", ".join(str(i) for i in silent)
                + " did not reply"
            )
        if unresolved:
            parts.append(
                "replies from " + ", ".join(unresolved)
                + " match no known device"
            )
        return "inconclusive", (
            "No divergence observed, but "
            + "; ".join(parts)
            + " — the live path is not fully verified."
        )

    @app.route("/api/paths/validate-live", methods=["POST"])
    def api_paths_validate_live():
        """Live validation of a recorded trace (packet trace Phase 3).

        Runs ONE real traceroute from the source device — an ACTIVE
        probe that sends packets, executed only on the operator's
        explicit request, gated as console.use, host-key-verified, and
        audited like a console connection. The result overlays the
        observed path on the engine's prediction; addresses Atlas
        cannot name and hops that stayed silent are reported as
        exactly that, never guessed into agreement.
        """

        from uuid import uuid4

        from founderos_atlas.console import (
            ConsoleHostKeyBlocked,
            ConsoleHostKeyUnknown,
            ConsoleSessionError,
            PING_SETTLED_NOTE,
            ProbeUnsupported,
            SILENT_HOP_NOTE,
            dataplane_address,
            parse_ping,
            parse_service_result,
            parse_traceroute,
            path_probe,
            ping_settled,
            platform_family,
            probe_hint,
            reachability_probe,
            run_probe_command,
            service_probe,
            silent_tail,
        )

        body = request.get_json(silent=True) or {}
        source = str(body.get("source") or "").strip()
        destination = str(body.get("destination") or "").strip()
        if not source or not destination:
            return {"error": "source and destination are required"}, 400

        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        report_dir = (
            enterprise_scope_dir(output_dir())
            if scope_id == GLOBAL_SCOPE_ID
            else scopes[scope_id].output_dir
        )
        # The probe validates a recorded prediction; it never invents one.
        predicted = load_json(report_dir / "path_investigation_report.json")
        predicted = predicted if isinstance(predicted, dict) else {}
        if (
            str(predicted.get("source") or "").casefold() != source.casefold()
            or str(predicted.get("destination") or "").casefold()
            != destination.casefold()
        ):
            return {
                "error": "Run a trace for this source and destination "
                "first — the live probe validates a recorded prediction."
            }, 409

        def _target_for(name):
            wanted = name.casefold()
            for target in console_targets(scopes, scope_id):
                if wanted in (
                    target.hostname.casefold(),
                    target.device_id.casefold(),
                ):
                    return target
            return None

        src = _target_for(source)
        if src is None:
            return {
                "error": f"No canonical device '{source}' in this scope."
            }, 404
        dst = _target_for(destination)
        if dst is None or not dst.management_ip:
            return {
                "error": f"{destination} has no verified management "
                "address to probe toward."
            }, 409
        if not src.eligible or not src.management_ip:
            return {"error": f"{source}: {src.reason}"}, 409
        if not src.credential_ref:
            return {
                "error": f"{source} has no stored credential to log in "
                "with."
            }, 409
        try:
            username, password = console_credential_for(
                scopes, scope_id, src.credential_ref
            )
        except KeyError:
            return {"error": "The stored credential reference is unknown."}, 409

        # Probe the forwarding plane the prediction is about. A
        # management address may be out-of-band (this is common — and
        # deliberate in many estates): tracerouting toward it would
        # validate the wrong network, or nothing at all.
        snapshot = load_json(report_dir / "topology_snapshot.json") or {}
        dataplane = dataplane_address(
            snapshot.get("devices"), dst.hostname, dst.management_ip
        )
        if dataplane is not None:
            target_address, target_interface = dataplane
            target_note = (
                f"its dataplane address {target_address} "
                f"({target_interface}) — the management address is not "
                "the plane the prediction is about"
            )
        else:
            target_address = dst.management_ip
            target_note = (
                f"its management address {target_address} — the snapshot "
                "records no other address for it, so this validates the "
                "management path"
            )

        family = platform_family(src.vendor, src.platform)
        # The declared protocol rides into the path probe: where the
        # CLI can be told, the probe sends what the operator asked
        # about instead of traceroute's UDP default.
        declared = predicted.get("intent") or {}
        probe = path_probe(
            target_address,
            family=family,
            protocol=str(declared.get("protocol") or "") or None,
        )
        command = probe.command
        probe_id = f"probe-{uuid4().hex[:12]}"

        def _record(result, detail):
            console_audit().record(
                "live-probe",
                session_id=probe_id,
                operator=current_actor(),
                device_id=src.device_id,
                hostname=src.hostname,
                management_ip=src.management_ip,
                port=src.port,
                credential_ref=src.credential_ref,
                result=result,
                detail=detail,
            )

        try:
            output = run_probe_command(
                host=src.management_ip,
                port=src.port,
                username=username,
                password=password,
                command=command,
                host_key_store=console_host_key_store(),
                client_factory=app.config.get("ATLAS_PROBE_CLIENT_FACTORY"),
                stop_when=silent_tail,
                stop_note=SILENT_HOP_NOTE,
            )
        except (ConsoleHostKeyBlocked, ConsoleHostKeyUnknown) as error:
            # The probe authenticates with a stored password, so it will
            # not send it to a host whose identity Atlas cannot vouch
            # for. Accepting a fingerprint is a security decision and
            # belongs where it can be made properly — the device's
            # console, which shows both fingerprints and requires an
            # explicit act — not behind a convenience button in a
            # troubleshooting panel, where it would be clicked through.
            _record("blocked", str(error))
            changed = isinstance(error, ConsoleHostKeyBlocked)
            return {
                "error": str(error),
                "host_key_problem": "changed" if changed else "unknown",
                "device_id": src.device_id,
                "console_url": url_for(
                    "console_page", device_id=src.device_id
                ),
                "guidance": (
                    (
                        f"{src.hostname} presented a different SSH host key "
                        "than the one Atlas trusted. A rebuilt or replaced "
                        "device does this, and so does an interception — "
                        "Atlas cannot tell them apart, so it stopped."
                        if changed else
                        f"Atlas has never accepted an SSH host key for "
                        f"{src.hostname}, so it will not send a stored "
                        "credential to it yet."
                    )
                    + " Open this device's console to compare the "
                    "fingerprints and accept the key if it is expected, "
                    "then run Validate live again."
                ),
            }, 409
        except ConsoleSessionError as error:
            _record("failed", str(error))
            return {"error": str(error)}, 502
        _record("ok", command)

        # The service check (Phase 3 extension): the path can deliver a
        # packet and the destination still refuse it. Those are
        # different facts and the trace answers only the first, so when
        # the recorded prediction declared a port, ask the second
        # question too — with a real TCP connect from the same device.
        declared_port = str(
            (predicted.get("intent") or {}).get("port") or ""
        ).strip()
        service = None
        if declared_port.isdigit():
            try:
                service_check = service_probe(
                    target_address, declared_port, family=family
                )
                check = service_check.command
            except ProbeUnsupported as unsupported:
                service = {
                    "state": "unsupported",
                    "command": None,
                    "detail": str(unsupported),
                    "output": "",
                }
            else:
                try:
                    service_output = run_probe_command(
                        host=src.management_ip,
                        port=src.port,
                        username=username,
                        password=password,
                        command=check,
                        host_key_store=console_host_key_store(),
                        command_timeout=20.0,
                        client_factory=app.config.get(
                            "ATLAS_PROBE_CLIENT_FACTORY"
                        ),
                    )
                except ConsoleSessionError as error:
                    _record("failed", f"{check}: {error}")
                    service = {
                        "state": "unknown",
                        "command": check,
                        "detail": str(error),
                        "output": "",
                    }
                else:
                    _record("ok", check)
                    state, evidence = parse_service_result(service_output)
                    service = {
                        "state": state,
                        "command": check,
                        "detail": _service_detail(
                            state, declared_port, dst.hostname, evidence
                        ),
                        "output": service_output,
                    }
                    hint = probe_hint(service_output)
                    if hint:
                        service["hint"] = hint

        # Name each replying address from snapshot evidence only.
        ip_map = {}
        for device in snapshot.get("devices") or ():
            if not isinstance(device, dict):
                continue
            hostname = str(device.get("hostname") or "")
            addresses = [device.get("management_ip")]
            addresses.extend(
                item.get("ip_address")
                for item in device.get("interfaces") or ()
                if isinstance(item, dict)
            )
            for value in addresses:
                if not value or not hostname:
                    continue
                address = str(value).split("/")[0].strip()
                if address:
                    ip_map.setdefault(address, hostname)

        hops = parse_traceroute(output)
        actual = [
            {
                **hop.to_dict(),
                "device": ip_map.get(hop.address) if hop.address else None,
            }
            for hop in hops
        ]

        # traceroute puts UDP on the wire whatever the operator
        # declared, and a routing CLI gives no way to change that. When
        # the probe did not reach the destination, that silence may be
        # about UDP and not about the declared traffic at all — so ask
        # the question again in a protocol Atlas can actually send.
        # Without this, a firewall permitting ICMP but dropping UDP
        # makes a healthy path read as broken.
        probe_protocol = probe.protocol
        named = {(entry["device"] or "").casefold() for entry in actual}
        addresses = {entry["address"] for entry in actual if entry["address"]}
        arrived = (
            dst.hostname.casefold() in named
            or target_address in addresses
        )
        reachability = None
        # Only worth asking when the path probe used something OTHER
        # than ICMP: if it already sent ICMP, a ping would repeat the
        # question it just answered.
        if not arrived and probe_protocol != "icmp":
            reach = reachability_probe(target_address, family=family)
            check = reach.command
            try:
                ping_output = run_probe_command(
                    host=src.management_ip,
                    port=src.port,
                    username=username,
                    password=password,
                    command=check,
                    host_key_store=console_host_key_store(),
                    command_timeout=15.0,
                    client_factory=app.config.get(
                        "ATLAS_PROBE_CLIENT_FACTORY"
                    ),
                    stop_when=ping_settled,
                    stop_note=PING_SETTLED_NOTE,
                )
            except ConsoleSessionError as error:
                _record("failed", f"{check}: {error}")
            else:
                _record("ok", check)
                state, evidence = parse_ping(ping_output)
                reachability = {
                    "state": state,
                    "protocol": reach.protocol,
                    "command": check,
                    "evidence": evidence,
                    "output": ping_output,
                    "detail": _reachability_detail(
                        state, dst.hostname, probe_protocol
                    ),
                }

        predicted_path = [str(item) for item in predicted.get("path") or ()]
        expected = [name.casefold() for name in predicted_path[1:]]
        if not actual:
            verdict = "inconclusive"
            hint = probe_hint(output)
            detail = (
                f"{src.hostname} returned no traceroute hops"
                + (f" — {hint}" if hint else
                   " — see the probe output for what the device said.")
            )
        else:
            verdict, detail = _probe_verdict(
                actual, expected, predicted_path, dst, target_address
            )
        # A protocol-correct probe that DID arrive settles the silence
        # the traceroute left: the path delivers, and what stopped is
        # the probe's own UDP. Saying "not verified" here would send an
        # engineer after an outage that is not happening.
        if (
            reachability
            and reachability["state"] == "reachable"
            and verdict != "diverged"
        ):
            detail = (
                f"The {probe_protocol.upper()} probes traceroute sends "
                f"were filtered before reaching {dst.hostname}, but an "
                f"ICMP probe reached it — the path does carry traffic "
                "to that host. " + detail
            )

        return {
            "probe": "active",
            "probe_note": (
                f"Live traceroute sent real packets from {src.hostname} "
                f"toward {dst.hostname}, probing {target_note}. Run at "
                "the operator's request."
            ),
            "command": command,
            "source": src.hostname,
            "destination": dst.hostname,
            "destination_address": target_address,
            "predicted_path": predicted_path,
            "hops": actual,
            "verdict": verdict,
            "verdict_detail": detail,
            "probe_protocol": probe_protocol,
            "reachability": reachability,
            "service": service,
            "output": output,
        }

    # -- Compass (PR-039: deterministic change planning) -----------------------

    def compass_repository():
        from founderos_atlas.compass import PlanRepository

        return PlanRepository(output_dir())

    @app.route("/compass")
    def compass_page():
        from founderos_atlas.compass import CHANGE_TYPES

        context, _scopes, _scope_id = scoped_context("compass")
        repository = compass_repository()
        show_archived = request.args.get("archived") == "1"
        plans = []
        archived_count = 0
        for plan in repository.list_plans():
            if plan.archived is not None:
                archived_count += 1
                if not show_archived:
                    continue
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
            archived_count=archived_count,
            show_archived=show_archived,
            change_types=CHANGE_TYPES,
            **context,
        )

    @app.route("/compass/<plan_id>/archive", methods=["POST"])
    def compass_archive(plan_id: str):
        """Mark a plan "taken care of": it leaves Home attention,
        Continue Working, and the default Compass list, but nothing is
        deleted — the record, its assessment, its audit trail, and the
        activity history all remain, and unarchive is one click."""

        from dataclasses import replace as _replace

        from founderos_atlas.audit import AuditEvent, AuditLog

        repository = compass_repository()
        plan, assessment = repository.get(plan_id)
        if plan is None:
            flash("That maintenance plan no longer exists.", "error")
            return redirect(url_for("compass_page"))
        unarchive = request.form.get("action") == "unarchive"
        if unarchive == (plan.archived is None):
            flash(
                "That plan is already "
                + ("active." if unarchive else "archived."),
                "warning",
            )
            return redirect(safe_redirect_target(
                request.form.get("next"), url_for("compass_page")
            ))
        marker = (
            None if unarchive
            else {"at": now_iso(), "by": current_actor()}
        )
        repository.save(_replace(plan, archived=marker), assessment)
        AuditLog(cfg("ATLAS_WORKSPACE_ROOT")).append(AuditEvent.create(
            category="compass-plan",
            operation="unarchive" if unarchive else "archive",
            subject=plan.plan_id,
            actor=current_actor(),
            before={"archived": plan.archived},
            after={"archived": marker},
            reason=str(request.form.get("reason") or "") or None,
        ))
        flash(
            f"Plan '{plan.title}' "
            + ("restored to the active list." if unarchive
               else "archived — kept in history, out of your way."),
            "success",
        )
        return redirect(safe_redirect_target(
            request.form.get("next"), url_for("compass_page")
        ))

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
            engineer=request.form.get("engineer", "") or current_actor(),
            cab_reference=request.form.get("cab_reference", "") or None,
            created_at=now_iso(),
        )
        incident_ref = request.form.get("incident_ref", "").strip()
        if incident_ref:
            from dataclasses import replace as _replace

            from founderos_atlas.incidents.records import (
                IncidentCaseRepository,
            )

            repository = compass_repository()
            linked, _assessment = repository.get(plan.plan_id)
            repository.save(_replace(linked, incident_ref=incident_ref))
            try:
                IncidentCaseRepository(cfg("ATLAS_WORKSPACE_ROOT")).link(
                    incident_ref, kind="plan", value=plan.plan_id,
                    actor=current_actor(),
                )
            except ValueError:
                pass
        flash(f"Plan '{plan.title}' created.", "success")
        # "Add to Compass" carried a device here; it rides into the plan
        # page so the Add-a-Change form arrives preselected.
        device = request.form.get("device", "").strip()
        reason = request.form.get("reason", "").strip()
        if device:
            return redirect(
                url_for(
                    "compass_plan_page", plan_id=plan.plan_id,
                    device=device, reason=reason or None,
                )
            )
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
        from founderos_atlas.compass.lifecycle import (
            change_checkpoints,
            readiness_gaps,
            validate_order,
        )

        return render_template(
            "compass_plan.html",
            readiness_gaps=readiness_gaps(plan),
            order_problems=validate_order(plan.changes),
            checkpoints=change_checkpoints(plan),
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
        _check_plan_revision(repository, plan_id)
        add_change(repository, plan, change, updated_at=now_iso())
        flash(f"Added: {change.title}.", "success")
        return redirect(url_for("compass_plan_page", plan_id=plan_id))

    def _check_plan_revision(repository, plan_id: str):
        """Optimistic concurrency for plan mutations (409 on stale form)."""

        from founderos_atlas.compass.service import PlanConflictError

        raw = request.form.get("expected_revision", "")
        expected = int(raw) if raw.strip().isdigit() else None
        try:
            return repository.check_revision(plan_id, expected)
        except PlanConflictError as error:
            abort(409, description=str(error))

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
        _check_plan_revision(repository, plan_id)
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
        _check_plan_revision(repository, plan_id)
        analyse_plan_for_workspace(
            repository,
            plan,
            base_output_dir=output_dir(),
            profiles=profile_service().list_profiles(),
            generated_at=now_iso(),
            catalog=SiteCatalogRepository(cfg("ATLAS_WORKSPACE_ROOT")).load(),
            credential_memory=CredentialSuccessMemory(cfg("ATLAS_WORKSPACE_ROOT")),
        )
        notify = app.config.get("ATLAS_NOTIFY_APPROVAL")
        if notify is not None:
            notify(plan_id, plan.title)
        flash("Plan analysed — approvers have been notified.", "success")
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
        # "Show all": ?group=<id> expands one group past the default
        # per-group limit; the cap keeps a runaway query bounded.
        group = request.args.get("group", "").strip()
        try:
            limit = int(request.args.get("limit", "") or 8)
        except ValueError:
            limit = 8
        limit = max(1, min(limit, 200))
        response = search_enterprise(
            current_search_index(), query, limit_per_group=limit
        )
        payload = response.to_dict()
        if group:
            payload["groups"] = [
                item for item in payload["groups"] if item["id"] == group
            ]
            payload["expanded_group"] = group
        return jsonify(payload)

    @app.route("/devices/<path:enterprise_id>")
    def device_details(enterprise_id: str):
        context, _scopes, _scope_id = scoped_context("topology")
        graph, _snapshot = enterprise_world()
        device = graph.device_by_id(enterprise_id)
        if device is None:
            # Stable hostname addressing: an enterprise id embeds a
            # management address that can change between discoveries, so
            # /devices/<hostname> is the shareable form. It resolves only
            # when exactly one canonical device carries the name — an
            # ambiguous name is answered with not-found, never a guess.
            wanted = enterprise_id.strip().casefold()
            matches = [
                candidate for candidate in graph.devices
                if str(candidate.hostname).casefold() == wanted
            ]
            if len(matches) == 1:
                device = matches[0]
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
        from founderos_atlas.incidents.records import (
            CASE_STATUSES,
            IncidentCaseRepository,
            SEVERITIES,
        )

        context, scopes, scope_id = scoped_context("incidents")
        repo = IncidentCaseRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        include_suppressed = request.args.get("suppressed") == "1"
        include_resolved = request.args.get("resolved") == "1"
        status = request.args.get("status", "").strip() or None
        list_scope = None if scope_id == GLOBAL_SCOPE_ID else scope_id
        cases = repo.list(
            scope_id=list_scope,
            include_suppressed=include_suppressed,
            status=status,
            include_resolved=include_resolved,
        )
        # Say what the default view is hiding, so "18 cases" never
        # silently becomes "9" without an explanation on the page.
        hidden_resolved = 0
        if not status and not include_resolved:
            hidden_resolved = sum(
                1 for case in repo.list(
                    scope_id=list_scope, include_suppressed=include_suppressed,
                ) if case.status == "resolved"
            )
        owner = request.args.get("owner", "").strip()
        if owner:
            cases = [case for case in cases if (case.owner or "") == owner]
        # Enterprise scope is never a dead end: investigations still run
        # against ONE observation point, chosen inline on the form.
        selectable = [
            {"scope_id": scope.scope_id, "label": scope.label}
            for scope in aggregation_scopes(scopes)
        ]
        scope = scopes.get(scope_id) if scope_id != GLOBAL_SCOPE_ID else None
        return render_template(
            "incidents.html",
            global_view=scope_id == GLOBAL_SCOPE_ID,
            cases=cases,
            case_filters={"status": status or "", "owner": owner,
                          "suppressed": include_suppressed,
                          "resolved": include_resolved},
            hidden_resolved=hidden_resolved,
            case_statuses=CASE_STATUSES,
            severities=SEVERITIES,
            selectable_profiles=selectable,
            report=(
                load_json(scope.output_dir / "incident_report.json")
                if scope else None
            ),
            root_cause=(
                (load_json(scope.output_dir / "root_cause_report.json") or {})
                .get("most_important") if scope else None
            ),
            artifact_prefix=artifact_prefix(scope) if scope else "",
            **context,
        )

    @app.route("/incidents/bulk", methods=["POST"])
    def incidents_bulk():
        """Resolve or suppress several cases in one audited action —
        every case keeps its evidence and history; the shared
        correlation id ties the batch together in the audit log."""

        from uuid import uuid4

        from founderos_atlas.incidents.records import (
            IncidentCaseRepository,
        )

        action = str(request.form.get("bulk_action") or "").strip()
        case_ids = [
            case_id for case_id in request.form.getlist("case_ids")
            if str(case_id or "").strip()
        ]
        reason = str(request.form.get("reason") or "").strip()
        next_url = safe_redirect_target(
            request.form.get("next"), scoped_url("/incidents")
        )
        if action not in ("resolve", "suppress") or not case_ids:
            flash("Select at least one case and choose an action.", "error")
            return redirect(next_url)
        if not reason:
            flash(
                "A reason is required — it becomes each case's "
                + ("resolution." if action == "resolve"
                   else "suppression reason."),
                "error",
            )
            return redirect(next_url)
        repo = IncidentCaseRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        correlation = f"bulk:{uuid4().hex}"
        done = 0
        skipped: list[str] = []
        for case_id in case_ids:
            try:
                if action == "resolve":
                    repo.resolve(
                        case_id, resolution=reason,
                        actor=current_actor(),
                        correlation_id=correlation,
                    )
                else:
                    repo.suppress(
                        case_id, reason=reason, actor=current_actor(),
                        correlation_id=correlation,
                    )
                done += 1
            except ValueError as error:
                skipped.append(f"{case_id}: {error}")
        message = (
            f"{done} case(s) {action}d (audited under one correlation id)."
        )
        if skipped:
            message += f" Skipped {len(skipped)}: " + "; ".join(skipped[:3])
        flash(message, "success" if done else "error")
        return redirect(next_url)

    @app.route("/incidents/run", methods=["POST"])
    def incidents_run():
        scopes = known_scopes()
        scope_id = active_scope_id(scopes)
        if scope_id == GLOBAL_SCOPE_ID:
            # Inline profile selection keeps the enterprise view useful:
            # the investigation runs against the chosen observation point.
            chosen = request.form.get("profile", "").strip()
            if chosen and chosen in scopes:
                scope_id = chosen
            else:
                flash(
                    "Choose which profile's evidence to investigate against.",
                    "error",
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
        from founderos_atlas.incidents.records import IncidentCaseRepository

        repo = IncidentCaseRepository(cfg("ATLAS_WORKSPACE_ROOT"))
        existing = repo.find_active(scope_id=scope.scope_id, title=title)
        if existing is not None:
            # Duplicate guard: the same investigation re-run attaches its
            # fresh report to the still-active case instead of opening an
            # identical new one — audited as a reinvestigation.
            case = repo.refresh_evidence(
                existing.case_id, report=report.to_dict(),
                actor=current_actor(),
            )
            flash(
                f"Re-investigated — the fresh report is now the evidence "
                f"of the existing open case '{case.title}' "
                "(no duplicate case was created).",
                "success",
            )
        else:
            case = repo.open_case(
                scope_id=scope.scope_id,
                scope_label=scope.label,
                title=title,
                description=description,
                severity=(
                    request.form.get("severity", "").strip() or "medium"
                ),
                actor=current_actor(),
                report=report.to_dict(),
            )
            flash(
                "Incident investigated and case opened — the report below "
                "is its evidence.",
                "success",
            )
        return redirect(url_for("incident_case_page", case_id=case.case_id))

    # -- Settings -----------------------------------------------------------

    def _administration_repository():
        return AdministrationRepository(cfg("ATLAS_WORKSPACE_ROOT"))

    def _administration_audit(operation: str, *, before=None, after=None, reason=None):
        from founderos_atlas.audit import AuditEvent, AuditLog
        AuditLog(cfg("ATLAS_WORKSPACE_ROOT")).append(AuditEvent.create(
            category="administration", operation=operation,
            subject="workspace-settings", before=before or {}, after=after or {},
            reason=reason, scope_id="all",
        ))

    @app.route("/settings")
    def settings():
        from .timefmt import AUTO, timezone_label
        from .system_info import collect_system_information

        provider = profile_service().credential_provider
        tz_setting = str(app.config.get("ATLAS_DISPLAY_TIMEZONE") or AUTO)
        preferences = _administration_repository().preferences()
        system_info = collect_system_information(
            app, credential_provider=provider, preferences=preferences,
        )
        context = {
            "display_timezone_setting": tz_setting,
            "display_timezone_label": timezone_label(display_timezone()),
            "display_timezone_is_auto": tz_setting.casefold() == AUTO,
            "workspace_root": str(cfg("ATLAS_WORKSPACE_ROOT")),
            "output_dir": str(output_dir()),
            "history_root": str(cfg("ATLAS_HISTORY_ROOT")),
            "preferences": preferences,
            "system_info": system_info,
        }
        return render_template("settings.html", **context, **base_context("settings"))

    @app.route("/api/preferences/ui")
    def api_ui_preference_get():
        """Read ONE of the current user's namespaced UI preferences
        (topology layers, table columns, workflow advanced-state)."""

        from founderos_atlas.workspace.user_preferences import (
            UserPreferenceStore,
        )

        key = str(request.args.get("key") or "").strip()
        store = UserPreferenceStore(cfg("ATLAS_WORKSPACE_ROOT"))
        if not any(
            key.startswith(prefix) for prefix in store.ALLOWED_UI_PREFIXES
        ):
            return jsonify(error="unknown preference namespace"), 400
        return jsonify(key=key, value=store.ui_value(current_actor(), key))

    @app.route("/api/preferences/ui", methods=["POST"])
    def api_ui_preference_set():
        """Write ONE namespaced UI preference for the CURRENT user.

        Personal presentation state only: namespaces are allowlisted and
        values size-capped in the store; nothing security-relevant can
        ride this channel, and it never touches another user's record.
        """

        from founderos_atlas.workspace.user_preferences import (
            UserPreferenceStore,
        )

        payload = request.get_json(silent=True) or {}
        try:
            UserPreferenceStore(cfg("ATLAS_WORKSPACE_ROOT")).set_ui_value(
                current_actor(),
                str(payload.get("key") or ""),
                payload.get("value"),
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(saved=True)

    @app.route("/preferences/display-level", methods=["POST"])
    def preferences_display_level():
        """Set the CURRENT user's display level (simple/detailed/expert).

        Personal, not workspace policy: any signed-in user (or the local
        operator) may set their own; it never touches another user's
        preference and never changes what RBAC allows — only how much
        detail pages open with.
        """

        from founderos_atlas.workspace.user_preferences import (
            UserPreferenceStore,
        )
        from .redirects import safe_redirect_target

        try:
            level = UserPreferenceStore(cfg("ATLAS_WORKSPACE_ROOT")).set_display_level(
                current_actor(), request.form.get("display_level", "")
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(
                safe_redirect_target(request.form.get("next"), "/settings")
            )
        _administration_audit(
            "display-level",
            after={"owner": current_actor(), "display_level": level},
            reason="Operator changed their display level",
        )
        flash(f"Display level set to {level}.", "success")
        return redirect(
            safe_redirect_target(request.form.get("next"), "/settings")
        )

    @app.route("/settings", methods=["POST"])
    def settings_update():
        from founderos_atlas.workspace.administration import (
            PreferencesConflictError,
        )

        repository = _administration_repository()
        before = repository.preferences()
        try:
            preferences = repository.save_preferences(
                expected_updated_at=(
                    request.form.get("expected_updated_at")
                    if "expected_updated_at" in request.form else None
                ),
                value={
                "timezone": request.form.get("timezone", "auto"),
                "theme": request.form.get("theme", "system"),
                "density": request.form.get("density", "comfortable"),
                "retention_days": request.form.get("retention_days", "365"),
                "log_level": request.form.get("log_level", "INFO"),
                },
            )
            app.config["ATLAS_DISPLAY_TIMEZONE"] = preferences.timezone
            app.logger.setLevel(preferences.log_level)
            _administration_audit(
                "update", before=before.__dict__, after=preferences.__dict__,
                reason=request.form.get("reason") or "Operator updated preferences",
            )
            flash("Settings saved.", "success")
        except PreferencesConflictError as error:
            abort(409, description=str(error))
        except (ValueError, OSError) as error:
            flash(str(error), "error")
        return redirect(url_for("settings"))

    @app.route("/settings/reset", methods=["POST"])
    def settings_reset():
        if request.form.get("confirm") != "RESET SETTINGS":
            flash("Type RESET SETTINGS to confirm.", "error")
            return redirect(url_for("settings"))
        before = _administration_repository().preferences()
        after = _administration_repository().reset_preferences()
        app.config["ATLAS_DISPLAY_TIMEZONE"] = after.timezone
        _administration_audit("reset", before=before.__dict__, after=after.__dict__,
                              reason=request.form.get("reason"))
        flash("Display and retention preferences reset. Network evidence was not deleted.", "success")
        return redirect(url_for("settings"))

    @app.route("/system")
    def system_information():
        return redirect(url_for("settings") + "#system-information")

    @app.route("/settings/diagnostics.json")
    def settings_diagnostics():
        from .system_info import collect_system_information

        provider = profile_service().credential_provider
        preferences = _administration_repository().preferences()
        system_info = collect_system_information(
            app, credential_provider=provider, preferences=preferences,
        )
        payload = {
            **system_info,
            "python": __import__("sys").version.split()[0],
            "profile_count": len(profile_service().list_profiles(include_archived=True)),
            "preferences": preferences.__dict__,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _administration_audit("export-diagnostics", after={"fields": sorted(payload)})
        response = jsonify(payload)
        response.headers["Content-Disposition"] = 'attachment; filename="atlas-diagnostics.json"'
        return response

    def _history_roots() -> dict:
        return {
            scope.scope_id: scope.history_root
            for scope in known_scopes().values()
        }

    def _retention_preview():
        from founderos_atlas.workspace.retention import build_preview

        return build_preview(
            history_roots=_history_roots(),
            retention_days=_administration_repository().preferences().retention_days,
            workspace_root=Path(cfg("ATLAS_WORKSPACE_ROOT")),
        )

    @app.route("/system/update")
    def system_update():
        from founderos_atlas.workspace.update_info import update_information

        return render_template(
            "system_update.html",
            info=update_information(cfg("ATLAS_WORKSPACE_ROOT")),
            **base_context("settings"),
        )

    @app.route("/settings/retention")
    def settings_retention():
        preview = _retention_preview()
        return render_template(
            "retention.html",
            preview=preview.to_dict(),
            retention_days=preview.retention_days,
            **base_context("settings"),
        )

    @app.route("/settings/retention/execute", methods=["POST"])
    def settings_retention_execute():
        from founderos_atlas.workspace.retention import execute_retention

        if request.form.get("confirm") != "DELETE OLD HISTORY":
            flash(
                "Type DELETE OLD HISTORY to confirm — nothing was deleted.",
                "error",
            )
            return redirect(url_for("settings_retention"))
        # Re-derive the preview at execution time so the deletion set is
        # exactly today's removable records, never a stale list.
        preview = _retention_preview()
        if not preview.removable:
            flash("No records are eligible for removal.", "success")
            return redirect(url_for("settings_retention"))
        _administration_audit("retention-start", after={
            "retention_days": preview.retention_days,
            "candidate_count": len(preview.removable),
        })
        manifest = execute_retention(
            history_roots=_history_roots(),
            preview=preview,
            workspace_root=Path(cfg("ATLAS_WORKSPACE_ROOT")),
            actor=current_actor(),
        )
        _administration_audit("retention-complete", after={
            "removed_count": manifest["removed_count"],
            "removed_bytes": manifest["removed_bytes"],
            "errors": len(manifest["errors"]),
        })
        flash(
            f"Retention complete: {manifest['removed_count']} record(s) "
            f"removed ({manifest['removed_bytes']} bytes). A deletion "
            "manifest was written under the workspace. Credentials, audit "
            "records, incidents, and plans were untouched.",
            "success",
        )
        return redirect(url_for("settings_retention"))

    @app.route("/settings/backup")
    def settings_backup():
        from flask import Response

        from founderos_atlas.workspace.backup import build_backup

        payload, manifest = build_backup(
            cfg("ATLAS_WORKSPACE_ROOT"),
        )
        _administration_audit("backup", after={
            "secrets_included": False,
            "file_count": len(manifest["files"]),
            "backup_schema_version": manifest["backup_schema_version"],
        })
        return Response(payload, content_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="atlas-workspace-backup.zip"'
        })

    @app.route("/settings/restore", methods=["POST"])
    def settings_restore():
        from founderos_atlas.workspace.restore import (
            MAX_ARCHIVE_BYTES,
            RestoreError,
            perform_restore,
        )

        # Refuse oversized uploads BEFORE reading the body.
        if (request.content_length or 0) > MAX_ARCHIVE_BYTES + 65536:
            _administration_audit(
                "restore", after={"outcome": "refused-oversize"},
            )
            flash(
                "Restore refused: the upload exceeds the "
                f"{MAX_ARCHIVE_BYTES // (1024 * 1024)} MB limit.",
                "error",
            )
            return redirect(url_for("settings"))
        upload = request.files.get("backup")
        if request.form.get("confirm") != "RESTORE METADATA" or not upload:
            flash("Choose a backup and type RESTORE METADATA to confirm.", "error")
            return redirect(url_for("settings"))
        try:
            result = perform_restore(
                cfg("ATLAS_WORKSPACE_ROOT"),
                upload.read(MAX_ARCHIVE_BYTES + 1),
            )
        except RestoreError as error:
            _administration_audit(
                "restore",
                after={"outcome": "refused"},
                reason=str(error)[:300],
            )
            flash(f"Restore refused safely: {error}", "error")
            return redirect(url_for("settings"))
        _administration_audit("restore", after={
            "outcome": "committed",
            "files": result.restored,
            "integrity_verified": result.verified,
            "snapshot": Path(result.snapshot_dir).name
            if result.snapshot_dir else None,
        }, reason=request.form.get("reason"))
        flash(
            f"Metadata restored ({len(result.restored)} file(s)), integrity "
            "verified. Sessions were not restored and no credential store "
            "was touched. Restart Atlas now so every in-memory view reloads "
            "the restored records; the pre-restore snapshot is retained "
            "under the workspace for recovery.",
            "success",
        )
        return redirect(url_for("settings"))

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

    def _credential_set_repo():
        from founderos_atlas.credentials.repository import CredentialSetRepository

        return CredentialSetRepository(Path(cfg("ATLAS_WORKSPACE_ROOT")))

    def _set_entries(set_ids=None):
        """Enabled credential-set entries, best first (lower priority wins).

        ``set_ids`` limits to a profile's named sets; None means every set.
        """

        try:
            sets = _credential_set_repo().load()
        except Exception:  # noqa: BLE001 - no sets is a state, not an error
            return []
        entries = []
        for set_id, credential_set in sorted(sets.items()):
            if set_ids is not None and set_id not in set_ids:
                continue
            for entry in credential_set.entries:
                if entry.enabled:
                    entries.append((credential_set, entry))
        entries.sort(key=lambda pair: (pair[1].priority, pair[0].set_id))
        return entries

    def _scope_login(scope):
        """(username, credential_ref, credential_name) for a scope.

        A set-only profile has no username and no credential_ref of its own —
        its way in is a credential set. Discovery learned this in PR-047A's
        follow-up ("a set-only profile connects with the set's credential");
        without the same fallback here, the console resolved such a scope to
        "<profile> (no user)" and every Connect died with
        "Choose a credential set" — even though the profile HAS chosen one.
        """

        profile = profile_for_scope(scope.scope_id)
        if profile is None:
            return None, None, None
        if profile.username and profile.credential_ref:
            return profile.username, profile.credential_ref, profile.name
        for credential_set, entry in _set_entries(set(profile.credential_sets)):
            return (
                entry.username,
                entry.credential_ref,
                f"{credential_set.name} — {entry.label}",
            )
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
        # Credential sets are choices too — for a set-only estate they are
        # the ONLY choices, and this list used to come back empty.
        for credential_set, entry in _set_entries():
            if entry.credential_ref in seen:
                continue
            seen.add(entry.credential_ref)
            choices.append(
                {
                    "credential_ref": entry.credential_ref,
                    "name": f"{credential_set.name} — {entry.label}",
                    "username": entry.username,
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
        # A set entry's reference resolves the same way: the ref names the
        # secret in the store, the entry carries the username beside it.
        for _credential_set, entry in _set_entries():
            if entry.credential_ref == credential_ref:
                password = profile_service().credential_provider.get(
                    credential_ref
                )
                return entry.username, password
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
        or has a verified web endpoint — both can change after any discovery
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
            # on — the same fallback the template helpers already offer.
            target = next(
                (t for t in targets if t.hostname.casefold() == hostname), None
            )
        # Web access is keyed by canonical device id; follow the ssh
        # resolution to it when the caller's id was a federated one.
        canonical_id = target.device_id if target is not None else wanted
        web = web_access_for(scopes, scope_id, canonical_id)
        if target is None and web is None:
            # Not a canonical device in this scope — an unresolved peer, or a
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
        from .linking import device_entity_actions, entity_url, scoped_url

        def _active_scope_for_links() -> str:
            cache = getattr(g, "_link_scope", None)
            if cache is None:
                try:
                    cache = active_scope_id(known_scopes())
                except Exception:  # noqa: BLE001 - a link must not 500 a page
                    cache = GLOBAL_SCOPE_ID
                g._link_scope = cache
            return cache

        def _draft_plan_for_links() -> str | None:
            cache = getattr(g, "_link_draft_plan", "unset")
            if cache == "unset":
                cache = None
                try:
                    from founderos_atlas.compass import PlanRepository

                    for plan in PlanRepository(output_dir()).list_plans():
                        if plan.status != "analysed":
                            cache = plan.plan_id
                            break
                except Exception:  # noqa: BLE001 - a link must not 500 a page
                    cache = None
                g._link_draft_plan = cache
            return cache

        def device_menu(hostname=None, device_id=None, name=None):
            """The canonical contextual-action menu for one device.

            The ONE builder every template uses (see web/linking.py): same
            actions, same order, same availability rules everywhere. The
            active scope is baked into every generated href so a copied
            link reopens the same entity in the same scope.
            """

            hostname = str(hostname or "").strip()
            if not hostname and not device_id:
                return []
            target = device_target(device_id=device_id, hostname=hostname)
            if not hostname and target:
                hostname = str(target.get("hostname") or "")
            actions = device_entity_actions(
                device_id=str(device_id or "").strip() or hostname or None,
                hostname=hostname or str(device_id or ""),
                scope_id=_active_scope_for_links(),
                ssh_target=target,
                draft_plan_id=_draft_plan_for_links(),
                entity_label=name,
            )
            return [action.to_dict() for action in actions]

        return {
            "device_target": device_target,
            "devices_mentioned": devices_mentioned,
            "web_access": web_access,
            "confidence_display": confidence_display,
            "confidence_detail": confidence_detail,
            "device_menu": device_menu,
            "entity_url": entity_url,
            "scoped_url": scoped_url,
            "link_scope": _active_scope_for_links,
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

    # Only the named report/viewer artifacts Atlas itself links to. The
    # output tree also holds evidence, jobs, and audit files — those have
    # their own routes with their own permissions, and this endpoint must
    # not become a side door around them.
    _ARTIFACT_BASENAMES = frozenset({
        "atlas_topology.html",
        "incident_report.md",
        "root_cause_report.md",
        "morning_brief.md",
        "path_investigation_report.md",
        "prediction_report.md",
        "change_report.md",
    })

    def past_path_investigations(scopes, scope_id):
        from founderos_atlas.path_intelligence import (
            load_investigation_history,
        )

        directory = (
            enterprise_scope_dir(output_dir())
            if scope_id == GLOBAL_SCOPE_ID
            else scopes[scope_id].output_dir
        )
        return load_investigation_history(directory)[:10]

    from types import SimpleNamespace as _NS

    from .lifecycle_routes import register_lifecycle_routes

    register_lifecycle_routes(app, _NS(
        cfg=cfg,
        current_actor=current_actor,
        scoped_context=scoped_context,
        known_scopes=known_scopes,
        active_scope_id=active_scope_id,
        aggregation_scopes=aggregation_scopes,
        scoped_world=scoped_world,
        output_dir=output_dir,
        now_iso=now_iso,
        load_json=load_json,
        artifact_prefix=artifact_prefix,
        past_path_investigations=past_path_investigations,
    ))

    @app.route("/artifacts/<path:name>")
    def artifacts(name: str):
        from flask import abort as _abort

        basename = name.rsplit("/", 1)[-1]
        if basename not in _ARTIFACT_BASENAMES:
            _abort(404)
        response = send_from_directory(str(output_dir()), name)
        if name.endswith("atlas_topology.html"):
            # The current viewer is derived mutable presentation over an
            # immutable snapshot. Browser caches must never resurrect an old
            # curation revision after the operator closes and reopens Atlas.
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


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
        # The profile's connect timeout reaches the real transport here;
        # None keeps the transport's own default. An injected (test/fake)
        # factory keeps its plain (credentials) contract.
        profile_timeout = getattr(
            app.config["ATLAS_PROFILE_SERVICE"].get_profile(profile_name),
            "connect_timeout_seconds", None,
        )
        if injected_factory is not None:
            base_factory = injected_factory
        elif profile_timeout is not None:
            def base_factory(credentials, _t=float(profile_timeout)):
                return SSHDeviceTransport(credentials, connect_timeout=_t)
        else:
            base_factory = SSHDeviceTransport

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
