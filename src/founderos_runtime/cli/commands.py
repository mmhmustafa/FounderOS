"""Thin public commands over existing FounderOS runtime components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import webbrowser

from founderos_atlas.change import (
    ChangeDetector,
    render_change_report_json,
    render_change_report_markdown,
)
from founderos_atlas.config import (
    AtlasConfigurationError,
    collect_configuration,
    safe_artifact_name,
    write_configuration_artifacts,
)
from founderos_atlas.config_intelligence import (
    compare_configurations,
    render_config_report_json,
    render_config_report_markdown,
)
from founderos_atlas.dashboard import DashboardRenderer, build_dashboard_summary
from founderos_atlas.history import (
    CONFIG_COLLECTED,
    CONFIG_FAILED,
    CONFIG_NOT_REQUESTED,
    CONFIG_PARTIAL,
    HistoryRepository,
    generate_timeline,
)
from founderos_atlas.incidents import (
    IncidentArtifacts,
    IncidentInvestigator,
    render_incident_report_json,
    render_incident_report_markdown,
)
from founderos_atlas.demo import run_atlas_discovery_demo
from founderos_atlas.discovery import AtlasDiscoveryError, DiscoveryResult, MultiHopConfig
from founderos_atlas.journeys import MorningBriefJourney, MorningBriefJourneyResult
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.pipeline import (
    aggregate_config_reports,
    load_previous_baseline,
    run_configuration_intelligence,
    run_operational_intelligence,
    run_topology_intelligence,
)
from founderos_atlas.state import (
    OperationalStateDetector,
    render_state_report_json,
    render_state_report_markdown,
)
from founderos_atlas.credentials import (
    CredentialCandidate,
    CredentialResolver,
    CredentialSetRepository,
    CredentialSuccessMemory,
    MultiCredentialTransportFactory,
)
from founderos_atlas.enterprise_intelligence import (
    IntelligenceEvidence,
    build_intelligence,
    intelligence_brief_section,
    render_intelligence_json,
    render_intelligence_markdown,
)
from founderos_atlas.root_cause import (
    analyze as analyze_root_cause,
    render_root_cause_json,
    render_root_cause_markdown,
    root_cause_brief_section,
    root_cause_incident_section,
)
from founderos_atlas.workspace import (
    AtlasWorkspaceError,
    DiscoveryScope,
    ProfileService,
    profile_id_for,
    profile_scope,
)
from founderos_atlas.topology import TopologyGraph, TopologySnapshot, TopologySnapshotExporter
from founderos_atlas.transport import (
    AtlasTransportError,
    DeviceCredentials,
    DeviceTransport,
    SSHDeviceTransport,
)
from founderos_atlas.visualization import TopologyRenderer
from founderos_runtime.demo import load_discovery_workspace, run_discovery_vertical_slice
from founderos_runtime.evaluation import EvaluationRunner
from founderos_runtime.journey import JourneyResult, JourneyStatus
from founderos_runtime.provider import MockProvider
from founderos_runtime.workspace import WorkspaceError

from .exceptions import CliError
from .render import (
    VERSION_TEXT,
    render_atlas_compare,
    render_atlas_config_diff,
    render_atlas_dashboard,
    render_atlas_discover,
    render_atlas_history,
    render_atlas_investigate,
    render_atlas_profile_detail,
    render_atlas_profile_list,
    render_atlas_profile_saved,
    render_atlas_state_diff,
    render_atlas_timeline,
    render_atlas_discovery,
    render_atlas_topology,
    render_atlas_morning_brief,
    render_discovery,
    render_doctor,
    render_help,
)


DiscoveryRunner = Callable[[], JourneyResult]
AtlasDiscoveryRunner = Callable[[], tuple[DiscoveryResult, TopologyGraph, TopologySnapshot]]
BrowserOpener = Callable[[str], object]
MorningBriefRunner = Callable[[TopologySnapshot, TopologySnapshot | None], MorningBriefJourneyResult]
TransportFactory = Callable[[DeviceCredentials], DeviceTransport]
PromptReader = Callable[[str], str]
Clock = Callable[[], datetime]


def version_command() -> tuple[int, str]:
    return 0, VERSION_TEXT


def help_command() -> tuple[int, str]:
    return 0, render_help()


def doctor_command() -> tuple[int, str]:
    checks = {
        "runtime": True,
        "manifests": False,
        "evaluation": False,
        "provider": False,
    }
    try:
        load_discovery_workspace()
        checks["manifests"] = True
    except (WorkspaceError, OSError, ValueError):
        pass
    checks["evaluation"] = isinstance(EvaluationRunner(), EvaluationRunner)
    checks["provider"] = isinstance(MockProvider(), MockProvider)
    return (0 if all(checks.values()) else 1), render_doctor(checks)


def discovery_command(
    runner: DiscoveryRunner = run_discovery_vertical_slice,
) -> tuple[int, str]:
    try:
        result = runner()
    except Exception as error:
        raise CliError(f"Discovery demo failed: {error}") from error
    if not isinstance(result, JourneyResult):
        raise CliError("Discovery demo returned an invalid result")
    return (0 if result.status is JourneyStatus.SUCCEEDED else 1), render_discovery(result)


def atlas_discovery_command(
    runner: AtlasDiscoveryRunner = run_atlas_discovery_demo,
) -> tuple[int, str]:
    try:
        result, graph, snapshot = runner()
    except (AtlasDiscoveryError, OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas Discovery demo failed: {error}") from error
    if (
        not isinstance(result, DiscoveryResult)
        or not isinstance(graph, TopologyGraph)
        or not isinstance(snapshot, TopologySnapshot)
    ):
        raise CliError("Atlas Discovery demo returned an invalid result")
    return 0, render_atlas_discovery(result, graph, snapshot)


def atlas_topology_command(
    runner: AtlasDiscoveryRunner = run_atlas_discovery_demo,
    *,
    output_path: str | Path = "atlas_topology.html",
    browser_opener: BrowserOpener | None = None,
) -> tuple[int, str]:
    try:
        _, _, snapshot = runner()
        if not isinstance(snapshot, TopologySnapshot):
            raise TypeError("Atlas topology demo returned an invalid snapshot")
        html = TopologyRenderer(snapshot).render()
        destination = Path(output_path).resolve()
        destination.write_text(html, encoding="utf-8")
        opener = browser_opener or webbrowser.open
        opener(destination.as_uri())
    except (AtlasDiscoveryError, OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas topology demo failed: {error}") from error
    return 0, render_atlas_topology(str(destination))


def atlas_discover_command(
    *,
    transport_factory: TransportFactory | None = None,
    input_reader: PromptReader | None = None,
    password_reader: PromptReader | None = None,
    journey_runner: MorningBriefRunner | None = None,
    topology_output: str | Path = "atlas_topology.html",
    snapshot_output: str | Path = "topology_snapshot.json",
    brief_output: str | Path = "morning_brief.md",
    config_output_dir: str | Path = "configs",
    dashboard_output: str | Path = "dashboard.html",
    history_root: str | Path = Path(".atlas") / "history",
    change_report_json_output: str | Path = "change_report.json",
    change_report_markdown_output: str | Path = "change_report.md",
    config_change_json_output: str | Path = "config_change_report.json",
    config_change_markdown_output: str | Path = "config_change_report.md",
    state_change_json_output: str | Path = "state_change_report.json",
    state_change_markdown_output: str | Path = "state_change_report.md",
    intelligence_json_output: str | Path | None = None,
    intelligence_markdown_output: str | Path | None = None,
    root_cause_json_output: str | Path | None = None,
    root_cause_markdown_output: str | Path | None = None,
    clock: Clock | None = None,
    browser_opener: BrowserOpener | None = None,
    progress: Callable[[str], None] | None = None,
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    """The unified Atlas pipeline: one command, the complete workflow."""

    read_input = input_reader or input
    read_password = password_reader or getpass.getpass
    read_clock = clock or (lambda: datetime.now(timezone.utc))
    emit = progress if progress is not None else (lambda line: print(line, flush=True))

    def step(number: int, label: str, status: str = "ok") -> None:
        emit(f"[{number}/9] {label} ... {status}")

    active_profile: str | None = None
    active_profile_id: str | None = None
    active_service: ProfileService | None = None
    collect_override: bool | None = None
    if profile is not None:
        active_service = _profile_service(profile_service)
        try:
            inputs = active_service.resolve_discovery_inputs(profile)
        except AtlasWorkspaceError as error:
            raise CliError(str(error)) from error
        active_profile = inputs.profile_name
        active_profile_id = inputs.profile_id or profile_id_for(inputs.profile_name)
        host, username, password = inputs.management_ip, inputs.username, inputs.password
        max_depth, max_devices = inputs.max_depth, inputs.max_devices
        collect_override = inputs.collect_configuration
        # Every profile discovers into its own isolated scope: its own
        # current artifacts, configs, and history. Comparison baselines can
        # therefore only ever come from the same profile's previous run.
        scope = profile_scope(
            Path(snapshot_output).parent, active_profile_id, active_profile
        )
        scope.output_dir.mkdir(parents=True, exist_ok=True)
        topology_output = scope.output_dir / Path(topology_output).name
        snapshot_output = scope.output_dir / Path(snapshot_output).name
        brief_output = scope.output_dir / Path(brief_output).name
        config_output_dir = scope.output_dir / Path(config_output_dir).name
        dashboard_output = scope.output_dir / Path(dashboard_output).name
        change_report_json_output = scope.output_dir / Path(change_report_json_output).name
        change_report_markdown_output = (
            scope.output_dir / Path(change_report_markdown_output).name
        )
        config_change_json_output = scope.output_dir / Path(config_change_json_output).name
        config_change_markdown_output = (
            scope.output_dir / Path(config_change_markdown_output).name
        )
        state_change_json_output = scope.output_dir / Path(state_change_json_output).name
        state_change_markdown_output = (
            scope.output_dir / Path(state_change_markdown_output).name
        )
        if intelligence_json_output is not None:
            intelligence_json_output = (
                scope.output_dir / Path(intelligence_json_output).name
            )
        if intelligence_markdown_output is not None:
            intelligence_markdown_output = (
                scope.output_dir / Path(intelligence_markdown_output).name
            )
        if root_cause_json_output is not None:
            root_cause_json_output = (
                scope.output_dir / Path(root_cause_json_output).name
            )
        if root_cause_markdown_output is not None:
            root_cause_markdown_output = (
                scope.output_dir / Path(root_cause_markdown_output).name
            )
        history_root = scope.history_root
        emit(f"Using profile: {active_profile}")
    else:
        try:
            host = read_input("Management IP: ").strip()
            username = read_input("Username: ").strip()
            password = read_password("Password: ")
        except (EOFError, KeyboardInterrupt) as error:
            raise CliError("Discovery was cancelled before connecting to a device") from error
        if not host or not username or not password:
            raise CliError("Management IP, username, and password are all required")
        max_depth = _read_limit(read_input, "Max depth [1]: ", 1)
        max_devices = _read_limit(read_input, "Max devices [10]: ", 10)
    # Intelligence artifacts live beside the run's other artifacts (already
    # profile-scoped above); a bare default would leak into the CWD when
    # callers inject every other path.
    if intelligence_json_output is None:
        intelligence_json_output = (
            Path(snapshot_output).parent / "intelligence_report.json"
        )
    if intelligence_markdown_output is None:
        intelligence_markdown_output = (
            Path(snapshot_output).parent / "intelligence_report.md"
        )
    if root_cause_json_output is None:
        root_cause_json_output = (
            Path(snapshot_output).parent / "root_cause_report.json"
        )
    if root_cause_markdown_output is None:
        root_cause_markdown_output = (
            Path(snapshot_output).parent / "root_cause_report.md"
        )
    started_at = read_clock()
    emit("")
    emit("Atlas Discovery Pipeline")
    try:
        config = MultiHopConfig(max_depth=max_depth, max_devices=max_devices)
        credentials = DeviceCredentials(host=host, username=username, password=password)
        build_transport = transport_factory or SSHDeviceTransport

        def host_transport(next_host: str) -> DeviceTransport:
            return build_transport(replace(credentials, host=next_host))

        # Profile runs resolve credentials per device: the profile's own
        # credential is the implicit first candidate, followed by any
        # scope-matching entries from the profile's credential sets —
        # bounded, deterministic, lockout-protected (PR-033).
        credential_factory: MultiCredentialTransportFactory | None = None
        on_neighbor = None
        active_boundary = active_seeds = None
        if profile is not None:
            active_boundary = inputs.boundary
            active_seeds = inputs.seeds
            workspace_root = active_service.repository.root
            credential_factory = MultiCredentialTransportFactory(
                base_factory=build_transport,
                resolver=CredentialResolver(
                    CredentialSetRepository(workspace_root),
                    CredentialSuccessMemory(workspace_root),
                ),
                credential_provider=active_service.credential_provider,
                set_ids=inputs.credential_sets,
                profile_id=active_profile_id,
                site_hint=inputs.site_hint,
                profile_default=CredentialCandidate(
                    credential_ref=inputs.credential_ref,
                    username=username,
                    label="profile credential",
                    priority=0,
                    source="profile-default",
                ),
                seed_hosts=(host, *(inputs.seeds or ())),
            )
            on_neighbor = credential_factory.prime_neighbor

        traversal_factory = credential_factory or host_transport
        report, graph, snapshot = run_multihop_discovery(
            traversal_factory,
            credentials.host,
            config=config,
            policy=active_boundary,
            extra_seeds=active_seeds or (),
            on_neighbor=on_neighbor,
        )
    except AtlasTransportError as error:
        raise CliError(str(error)) from error
    except (AtlasDiscoveryError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise CliError(f"Atlas live discovery failed: {error}") from error
    step(1, "Connecting to seed device")
    step(
        2,
        "Discovering topology",
        f"ok ({len(report.connected)} device(s), {len(report.failed)} failed)",
    )

    config_collections = _collect_configurations_if_requested(
        read_input,
        build_transport,
        credentials,
        report,
        config_output_dir,
        collect_override=collect_override,
        host_factory=credential_factory,
    )
    if config_collections is None:
        step(3, "Collecting configurations", "skipped (not requested)")
    else:
        step(3, "Collecting configurations", f"ok ({len(config_collections)} device(s))")
    completed_at = read_clock()

    baseline = load_previous_baseline(history_root)
    if baseline.available:
        step(4, "Loading previous baseline", f"ok ({baseline.record.record_id})")
    else:
        step(4, "Loading previous baseline", "skipped (first discovery)")

    topology_report = run_topology_intelligence(baseline, snapshot)
    state_report = run_operational_intelligence(baseline, snapshot)
    if topology_report is None:
        step(5, "Comparing topology & state", "skipped (no baseline)")
    else:
        step(
            5,
            "Comparing topology & state",
            f"ok ({topology_report.change_count} topology change(s), "
            f"{state_report.active_issue_count} active / "
            f"{state_report.change_count} operational event(s))",
        )

    collected_dirs = {
        hostname: detail
        for hostname, status, detail in (config_collections or ())
        if status != "failed"
    }
    config_reports = run_configuration_intelligence(
        history_root, baseline, collected_dirs
    )
    if not collected_dirs or baseline.record is None:
        step(6, "Comparing configurations", "skipped (no baseline configurations)")
    else:
        step(
            6,
            "Comparing configurations",
            f"ok ({sum(r.change_count for r in config_reports)} change(s) "
            f"across {len(config_reports)} device(s))",
        )

    try:
        pipeline_lines, destinations, brief = _build_reports(
            snapshot,
            baseline,
            topology_report,
            state_report,
            config_reports,
            collected_dirs,
            journey_runner,
            report,
            graph,
            config_collections,
            started_at,
            completed_at,
            topology_output,
            snapshot_output,
            brief_output,
            change_report_json_output,
            change_report_markdown_output,
            config_change_json_output,
            config_change_markdown_output,
            state_change_json_output,
            state_change_markdown_output,
            intelligence_json_output=intelligence_json_output,
            intelligence_markdown_output=intelligence_markdown_output,
            root_cause_json_output=root_cause_json_output,
            root_cause_markdown_output=root_cause_markdown_output,
            history_root=history_root,
        )
        opener = browser_opener or webbrowser.open
        opener(destinations["topology"].as_uri())
    except (AtlasDiscoveryError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise CliError(f"Atlas live discovery failed: {error}") from error
    step(7, "Building reports")

    history_line, record_id = _save_history(
        history_root,
        started_at,
        completed_at,
        report,
        graph,
        snapshot,
        brief,
        config_collections,
        destinations,
        profile_id=active_profile_id,
        profile_name=active_profile,
        credential_use=(
            dict(credential_factory.used_refs)
            if credential_factory is not None
            else None
        ),
    )
    step(8, "Archiving discovery", "ok" if record_id is not None else "failed")

    dashboard_line = _regenerate_dashboard(
        dashboard_output,
        destinations["topology"],
        destinations["snapshot"],
        destinations["brief"],
        config_output_dir,
        history_root,
    )
    if record_id is not None:
        HistoryRepository(history_root).attach_artifact(
            record_id, Path(dashboard_output).resolve()
        )
    step(9, "Updating dashboard")
    if active_service is not None and active_profile is not None:
        try:
            active_service.record_discovery(active_profile, completed_at)
        except AtlasWorkspaceError:
            # Recording the timestamp is best-effort; never fail a good run.
            pass
    emit("")
    emit("Discovery Complete")
    emit("")

    return 0, render_atlas_discover(
        report,
        graph,
        snapshot,
        brief,
        str(destinations["topology"]),
        str(destinations["snapshot"]),
        str(destinations["brief"]),
        config_collections=config_collections,
        dashboard_line=dashboard_line,
        history_line=history_line,
        pipeline_lines=tuple(pipeline_lines),
    )


def _build_reports(
    snapshot,
    baseline,
    topology_report,
    state_report,
    config_reports,
    collected_dirs,
    journey_runner,
    report,
    graph,
    config_collections,
    started_at,
    completed_at,
    topology_output,
    snapshot_output,
    brief_output,
    change_report_json_output,
    change_report_markdown_output,
    config_change_json_output,
    config_change_markdown_output,
    state_change_json_output,
    state_change_markdown_output,
    *,
    intelligence_json_output: str | Path = "intelligence_report.json",
    intelligence_markdown_output: str | Path = "intelligence_report.md",
    root_cause_json_output: str | Path = "root_cause_report.json",
    root_cause_markdown_output: str | Path = "root_cause_report.md",
    history_root: str | Path = Path(".atlas") / "history",
):
    """Write every artifact of the run; returns summary lines and paths."""

    pipeline_lines: list[str] = []
    destinations: dict[str, Path] = {}
    config_aggregate: dict | None = None

    if baseline.record is not None:
        pipeline_lines.append(f"Baseline: {baseline.record.record_id}")
    else:
        pipeline_lines.append("Baseline: none (first discovery)")
    pipeline_lines.extend(baseline.issues)

    if state_report is not None:
        json_destination = Path(state_change_json_output).resolve()
        json_destination.write_text(
            render_state_report_json(state_report), encoding="utf-8"
        )
        markdown_destination = Path(state_change_markdown_output).resolve()
        markdown_destination.write_text(
            render_state_report_markdown(state_report), encoding="utf-8"
        )
        destinations["state_change_report.json"] = json_destination
        destinations["state_change_report.md"] = markdown_destination
        pipeline_lines.append(
            f"Operational: current health {state_report.current_health}, "
            f"{state_report.active_issue_count} active issue(s), "
            f"{len(state_report.recoveries)} recovery(ies), "
            f"{state_report.change_count} event(s) (saved: {json_destination})"
        )

    if topology_report is not None:
        json_destination = Path(change_report_json_output).resolve()
        json_destination.write_text(
            render_change_report_json(topology_report), encoding="utf-8"
        )
        markdown_destination = Path(change_report_markdown_output).resolve()
        markdown_destination.write_text(
            render_change_report_markdown(topology_report), encoding="utf-8"
        )
        destinations["change_report.json"] = json_destination
        destinations["change_report.md"] = markdown_destination
        pipeline_lines.append(
            f"Topology changes: {topology_report.change_count} "
            f"(saved: {json_destination})"
        )
    else:
        pipeline_lines.append("Topology changes: no baseline to compare against")

    config_change_lines: dict[str, str] = {}
    if config_reports:
        aggregate, markdown = aggregate_config_reports(config_reports)
        config_aggregate = aggregate
        json_destination = Path(config_change_json_output).resolve()
        json_destination.write_text(
            json.dumps(aggregate, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        markdown_destination = Path(config_change_markdown_output).resolve()
        markdown_destination.write_text(markdown, encoding="utf-8")
        destinations["config_change_report.json"] = json_destination
        destinations["config_change_report.md"] = markdown_destination
        pipeline_lines.append(
            f"Configuration changes: {aggregate['change_count']} across "
            f"{aggregate['devices_changed']} device(s) (saved: {json_destination})"
        )
        config_change_lines = {
            item.hostname: f"{item.change_count} change(s)"
            for item in config_reports
        }
    elif collected_dirs:
        pipeline_lines.append(
            "Configuration changes: no baseline configurations to compare against"
        )

    viewer_context = {
        "last_discovered": completed_at.isoformat(timespec="seconds"),
        "configured_hostnames": tuple(sorted(collected_dirs, key=str.casefold)),
        "config_changes": config_change_lines,
    }
    html = TopologyRenderer(
        snapshot, change_report=topology_report, viewer_context=viewer_context
    ).render()
    topology_destination = Path(topology_output).resolve()
    topology_destination.write_text(html, encoding="utf-8")
    destinations["topology"] = topology_destination
    destinations["atlas_topology.html"] = topology_destination

    snapshot_destination = Path(snapshot_output).resolve()
    snapshot_destination.write_text(
        TopologySnapshotExporter(snapshot).to_json() + "\n", encoding="utf-8"
    )
    destinations["snapshot"] = snapshot_destination
    destinations["topology_snapshot.json"] = snapshot_destination

    run_context = {
        "devices": graph.summary()["device_count"],
        "relationships": _logical_relationships(graph),
        "configurations_collected": len(collected_dirs),
        "topology_changes": (
            topology_report.change_count if topology_report is not None else None
        ),
        "configuration_changes": sum(r.change_count for r in config_reports),
        "operational_changes": (
            state_report.change_count if state_report is not None else None
        ),
        "operational_active": (
            state_report.active_issue_count if state_report is not None else None
        ),
        "operational_recoveries": (
            len(state_report.recoveries) if state_report is not None else 0
        ),
        "interfaces_down": (
            state_report.interfaces_down if state_report is not None else 0
        ),
        "failures": len(report.failed),
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "duration_seconds": round(
            max(0.0, (completed_at - started_at).total_seconds()), 1
        ),
    }
    # Enterprise intelligence: turn this run's facts into what matters.
    # Deterministic and fully explained; archived with every other artifact
    # so trends can compare runs.
    repository = HistoryRepository(history_root)
    recent_records = repository.load().records[:5]
    previous_intelligence = None
    if baseline.record is not None:
        previous_path = (
            repository.record_directory(baseline.record.record_id)
            / "intelligence_report.json"
        )
        if previous_path.is_file():
            try:
                previous_intelligence = json.loads(
                    previous_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                previous_intelligence = None
    evidence = IntelligenceEvidence(
        generated_at=completed_at.isoformat(timespec="seconds"),
        snapshot=snapshot.to_dict(),
        previous_snapshot=(
            baseline.snapshot.to_dict() if baseline.snapshot is not None else None
        ),
        state_report=state_report.to_dict() if state_report is not None else None,
        topology_report=(
            topology_report.to_dict() if topology_report is not None else None
        ),
        config_report=config_aggregate,
        incident_report=None,  # incidents weigh in on later (GUI) evaluations
        failed_hosts=tuple(visit.host for visit in report.failed),
        failed_details=tuple(
            (visit.host, visit.detail) for visit in report.failed
        ),
        recent_records=recent_records,
        previous_intelligence=previous_intelligence,
        last_completed_at=completed_at.isoformat(timespec="seconds"),
        baseline_available=baseline.available,
    )
    intelligence = build_intelligence(evidence)
    intelligence_json_destination = Path(intelligence_json_output).resolve()
    intelligence_json_destination.write_text(
        render_intelligence_json(intelligence), encoding="utf-8"
    )
    intelligence_markdown_destination = Path(intelligence_markdown_output).resolve()
    intelligence_markdown_destination.write_text(
        render_intelligence_markdown(intelligence), encoding="utf-8"
    )
    destinations["intelligence_report.json"] = intelligence_json_destination
    destinations["intelligence_report.md"] = intelligence_markdown_destination
    pipeline_lines.append(
        f"Intelligence: health {intelligence.health.score}/100 "
        f"({intelligence.trend}), {len(intelligence.priorities)} priority "
        f"finding(s) (saved: {intelligence_json_destination})"
    )

    # Root cause analysis: explain WHY, deterministically, from the same
    # evidence — archived so history can replay yesterday's explanation.
    root_cause = analyze_root_cause(
        generated_at=completed_at.isoformat(timespec="seconds"),
        state_report=evidence.state_report,
        topology_report=evidence.topology_report,
        config_report=evidence.config_report,
        failed_details=evidence.failed_details,
        previous_snapshot=evidence.previous_snapshot,
        recurring_hosts=evidence.recurring_unstable_hosts,
    )
    root_cause_json_destination = Path(root_cause_json_output).resolve()
    root_cause_json_destination.write_text(
        render_root_cause_json(root_cause), encoding="utf-8"
    )
    root_cause_markdown_destination = Path(root_cause_markdown_output).resolve()
    root_cause_markdown_destination.write_text(
        render_root_cause_markdown(root_cause), encoding="utf-8"
    )
    destinations["root_cause_report.json"] = root_cause_json_destination
    destinations["root_cause_report.md"] = root_cause_markdown_destination
    most_important = root_cause.most_important
    if most_important is not None:
        pipeline_lines.append(
            f"Root cause: {most_important.primary.statement} "
            f"({most_important.primary.band} confidence) "
            f"(saved: {root_cause_json_destination})"
        )
    else:
        pipeline_lines.append(
            f"Root cause: nothing to explain (saved: {root_cause_json_destination})"
        )

    if journey_runner is not None:
        brief = journey_runner(snapshot, baseline.snapshot)
    else:
        brief = MorningBriefJourney().run(
            snapshot, baseline.snapshot, run_context=run_context
        )
    if not isinstance(brief, MorningBriefJourneyResult):
        raise TypeError("Atlas Morning Brief returned an invalid result")
    brief_destination = Path(brief_output).resolve()
    # Morning Brief v2: intelligence + the most important root cause.
    brief_destination.write_text(
        brief.markdown
        + intelligence_brief_section(intelligence)
        + root_cause_brief_section(root_cause),
        encoding="utf-8",
    )
    destinations["brief"] = brief_destination
    destinations["morning_brief.md"] = brief_destination

    return pipeline_lines, destinations, brief


def atlas_config_diff_command(
    previous_path: str | Path | None = None,
    current_path: str | Path | None = None,
    *,
    latest_hostname: str | None = None,
    history_root: str | Path = Path(".atlas") / "history",
    json_output: str | Path = "config_change_report.json",
    markdown_output: str | Path = "config_change_report.md",
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    if profile is not None:
        scope = _resolve_profile_scope(
            profile, profile_service, Path(json_output).parent
        )
        history_root = scope.history_root
        json_output = _scoped_path(json_output, scope)
        markdown_output = _scoped_path(markdown_output, scope)
        scope.output_dir.mkdir(parents=True, exist_ok=True)
    if latest_hostname is not None:
        previous_path, current_path, previous_ref, current_ref, hostname = (
            _latest_config_pair(history_root, latest_hostname)
        )
    else:
        if previous_path is None or current_path is None:
            raise CliError("Both a previous and a current configuration path are required")
        previous_ref, current_ref = str(previous_path), str(current_path)
        parent = Path(current_path).resolve().parent.name
        hostname = parent if parent and parent != "configs" else "device"
    previous_text = _read_config_file(previous_path)
    current_text = _read_config_file(current_path)
    try:
        report = compare_configurations(
            previous_text,
            current_text,
            hostname=hostname,
            previous_ref=previous_ref,
            current_ref=current_ref,
        )
        json_destination = Path(json_output).resolve()
        json_destination.write_text(render_config_report_json(report), encoding="utf-8")
        markdown_destination = Path(markdown_output).resolve()
        markdown_destination.write_text(
            render_config_report_markdown(report), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas configuration comparison failed: {error}") from error
    return 0, render_atlas_config_diff(
        report, str(json_destination), str(markdown_destination)
    )


def _latest_config_pair(
    history_root: str | Path, hostname: str
) -> tuple[Path, Path, str, str, str]:
    repository = HistoryRepository(history_root)
    safe_name = safe_artifact_name(hostname)
    matches: list[tuple[str, Path]] = []
    for record in repository.load().records:  # newest first
        candidate = (
            repository.record_directory(record.record_id)
            / "configs"
            / safe_name
            / "running_config.txt"
        )
        if candidate.is_file():
            matches.append((record.record_id, candidate))
        if len(matches) == 2:
            break
    if len(matches) < 2:
        raise CliError(
            f"History holds {len(matches)} collected configuration(s) for "
            f"{hostname}; two are required. Run discovery with configuration "
            "collection to build history."
        )
    (current_id, current_file), (previous_id, previous_file) = matches
    return previous_file, current_file, previous_id, current_id, hostname


def _read_config_file(path: str | Path) -> str:
    resolved = Path(path)
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise CliError(f"Could not read configuration file {resolved}: {error}") from error


def atlas_state_diff_command(
    previous_path: str | Path | None = None,
    current_path: str | Path | None = None,
    *,
    latest: bool = False,
    history_root: str | Path = Path(".atlas") / "history",
    json_output: str | Path = "state_change_report.json",
    markdown_output: str | Path = "state_change_report.md",
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    if profile is not None:
        scope = _resolve_profile_scope(
            profile, profile_service, Path(json_output).parent
        )
        history_root = scope.history_root
        json_output = _scoped_path(json_output, scope)
        markdown_output = _scoped_path(markdown_output, scope)
        scope.output_dir.mkdir(parents=True, exist_ok=True)
    if latest:
        previous_path, current_path, previous_ref, current_ref = _latest_snapshot_pair(
            history_root
        )
    else:
        if previous_path is None or current_path is None:
            raise CliError("Both a previous and a current snapshot path are required")
        previous_ref, current_ref = str(previous_path), str(current_path)
    previous = _load_snapshot_json(previous_path)
    current = _load_snapshot_json(current_path)
    try:
        report = OperationalStateDetector().compare(
            previous, current, previous_ref=previous_ref, current_ref=current_ref
        )
        json_destination = Path(json_output).resolve()
        json_destination.write_text(render_state_report_json(report), encoding="utf-8")
        markdown_destination = Path(markdown_output).resolve()
        markdown_destination.write_text(
            render_state_report_markdown(report), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas operational state comparison failed: {error}") from error
    return 0, render_atlas_state_diff(
        report, str(json_destination), str(markdown_destination)
    )


def _latest_snapshot_pair(history_root: str | Path) -> tuple[Path, Path, str, str]:
    repository = HistoryRepository(history_root)
    matches: list[tuple[str, Path]] = []
    for record in repository.load().records:  # newest first
        candidate = repository.snapshot_path(record.record_id)
        if candidate.is_file():
            matches.append((record.record_id, candidate))
        if len(matches) == 2:
            break
    if len(matches) < 2:
        raise CliError(
            f"History holds {len(matches)} snapshot(s); two are required for a "
            "state comparison. Run discovery to build history."
        )
    (current_id, current_file), (previous_id, previous_file) = matches
    return previous_file, current_file, previous_id, current_id


def _load_snapshot_json(path: str | Path) -> dict:
    resolved = Path(path)
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except OSError as error:
        raise CliError(f"Could not read snapshot file {resolved}: {error}") from error
    except json.JSONDecodeError as error:
        raise CliError(f"{resolved} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise CliError(f"{resolved} does not contain a topology snapshot object")
    return data


ProfileServiceFactory = Callable[[], ProfileService]


def _profile_service(service: ProfileService | None) -> ProfileService:
    if service is not None:
        return service
    try:
        return ProfileService()
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error


def _resolve_profile_scope(
    profile: str, service: ProfileService | None, base_dir: str | Path
) -> DiscoveryScope:
    """The isolated workspace of a saved profile, addressed by name."""

    resolved = _profile_service(service)
    try:
        found = resolved.get_profile(profile)
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    return profile_scope(base_dir, found.profile_id, found.name)


def _scoped_path(path: str | Path, scope: DiscoveryScope) -> Path:
    return scope.output_dir / Path(path).name


def atlas_profile_add_command(
    *,
    input_reader: PromptReader | None = None,
    password_reader: PromptReader | None = None,
    service: ProfileService | None = None,
) -> tuple[int, str]:
    read_input = input_reader or input
    read_password = password_reader or getpass.getpass
    service = _profile_service(service)
    try:
        name = read_input("Profile name: ").strip()
        site = read_input("Site name [optional]: ").strip() or None
        management_ip = read_input("Management IP: ").strip()
        username = read_input("Username: ").strip()
        password = read_password("Password: ")
        max_depth = _read_limit(read_input, "Max depth [1]: ", 1)
        max_devices = _read_limit(read_input, "Max devices [10]: ", 10)
        collect = _read_yes_no(read_input, "Collect running configuration? [y/N] ")
    except (EOFError, KeyboardInterrupt) as error:
        raise CliError("Profile creation was cancelled") from error
    try:
        profile = service.add_profile(
            name=name,
            site=site,
            management_ip=management_ip,
            username=username,
            password=password,
            max_depth=max_depth,
            max_devices=max_devices,
            collect_configuration=collect,
        )
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    return 0, render_atlas_profile_saved(profile, action="saved")


def atlas_profile_list_command(
    *, service: ProfileService | None = None
) -> tuple[int, str]:
    service = _profile_service(service)
    try:
        profiles = service.list_profiles()
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    return 0, render_atlas_profile_list(profiles)


def atlas_profile_show_command(
    name: str, *, service: ProfileService | None = None
) -> tuple[int, str]:
    service = _profile_service(service)
    try:
        profile = service.get_profile(name)
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    return 0, render_atlas_profile_detail(profile)


def atlas_profile_update_command(
    name: str,
    *,
    input_reader: PromptReader | None = None,
    password_reader: PromptReader | None = None,
    service: ProfileService | None = None,
) -> tuple[int, str]:
    read_input = input_reader or input
    read_password = password_reader or getpass.getpass
    service = _profile_service(service)
    try:
        existing = service.get_profile(name)
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    try:
        site = read_input(f"Site name [{existing.site or 'none'}]: ").strip()
        management_ip = read_input(f"Management IP [{existing.management_ip}]: ").strip()
        username = read_input(f"Username [{existing.username}]: ").strip()
        password = read_password("Password [keep current]: ")
        depth_text = read_input(f"Max depth [{existing.max_depth}]: ").strip()
        devices_text = read_input(f"Max devices [{existing.max_devices}]: ").strip()
        collect_text = read_input(
            f"Collect running configuration? [{_yes_no(existing.collect_configuration)}] "
        ).strip()
    except (EOFError, KeyboardInterrupt) as error:
        raise CliError("Profile update was cancelled") from error
    try:
        profile = service.update_profile(
            name,
            management_ip=management_ip or None,
            username=username or None,
            password=password or None,
            site=site or None,
            max_depth=int(depth_text) if depth_text else None,
            max_devices=int(devices_text) if devices_text else None,
            collect_configuration=(
                _parse_yes_no(collect_text) if collect_text else None
            ),
        )
    except ValueError as error:
        raise CliError(f"Invalid numeric input: {error}") from error
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    return 0, render_atlas_profile_saved(profile, action="updated")


def atlas_profile_delete_command(
    name: str, *, service: ProfileService | None = None
) -> tuple[int, str]:
    service = _profile_service(service)
    try:
        removed = service.delete_profile(name)
    except AtlasWorkspaceError as error:
        raise CliError(str(error)) from error
    return 0, f"Profile {removed.name!r} deleted."


def _read_yes_no(read_input: PromptReader, prompt: str) -> bool:
    try:
        return _parse_yes_no(read_input(prompt).strip())
    except (EOFError, KeyboardInterrupt):
        return False


def _parse_yes_no(text: str) -> bool:
    return text.strip().casefold() in ("y", "yes")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def atlas_investigate_command(
    *,
    input_reader: PromptReader | None = None,
    clock: Clock | None = None,
    snapshot_path: str | Path = "topology_snapshot.json",
    change_report_json: str | Path = "change_report.json",
    config_change_report: str | Path = "config_change_report.json",
    brief_path: str | Path = "morning_brief.md",
    configs_dir: str | Path = "configs",
    history_root: str | Path = Path(".atlas") / "history",
    json_output: str | Path = "incident_report.json",
    markdown_output: str | Path = "incident_report.md",
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    if profile is not None:
        scope = _resolve_profile_scope(
            profile, profile_service, Path(snapshot_path).parent
        )
        snapshot_path = _scoped_path(snapshot_path, scope)
        change_report_json = _scoped_path(change_report_json, scope)
        config_change_report = _scoped_path(config_change_report, scope)
        brief_path = _scoped_path(brief_path, scope)
        configs_dir = scope.output_dir / Path(configs_dir).name
        history_root = scope.history_root
        json_output = _scoped_path(json_output, scope)
        markdown_output = _scoped_path(markdown_output, scope)
        scope.output_dir.mkdir(parents=True, exist_ok=True)
    read_input = input_reader or input
    read_clock = clock or (lambda: datetime.now(timezone.utc))
    try:
        title = read_input("Incident title: ").strip()
        description = read_input("Incident description: ").strip()
    except (EOFError, KeyboardInterrupt) as error:
        raise CliError("Investigation was cancelled") from error
    if not title:
        raise CliError("An incident title is required")
    try:
        artifacts = IncidentArtifacts.load(
            snapshot_path=snapshot_path,
            change_report_json=change_report_json,
            config_change_report=config_change_report,
            brief_path=brief_path,
            configs_dir=configs_dir,
            history_root=history_root,
        )
        report = IncidentInvestigator().investigate(
            title,
            description,
            artifacts,
            generated_at=read_clock().isoformat(timespec="seconds"),
        )
        json_destination = Path(json_output).resolve()
        json_destination.write_text(render_incident_report_json(report), encoding="utf-8")
        markdown_destination = Path(markdown_output).resolve()
        incident_markdown = render_incident_report_markdown(report)
        # Every investigation automatically carries the run's root cause
        # analysis when one exists (PR-035).
        root_cause_path = Path(snapshot_path).parent / "root_cause_report.json"
        if root_cause_path.is_file():
            try:
                root_cause_data = json.loads(
                    root_cause_path.read_text(encoding="utf-8")
                )
                incident_markdown += root_cause_incident_section(root_cause_data)
            except (OSError, json.JSONDecodeError):
                pass
        markdown_destination.write_text(incident_markdown, encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas incident investigation failed: {error}") from error
    return 0, render_atlas_investigate(
        report, str(json_destination), str(markdown_destination)
    )


def atlas_web_command(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    output_dir: str | Path | None = None,
    history_root: str | Path | None = None,
    browser_opener: BrowserOpener | None = None,
    server_runner: Callable[..., None] | None = None,
) -> tuple[int, str]:
    """Start the local Atlas web GUI (binds to 127.0.0.1 only)."""

    try:
        from founderos_atlas.web import create_app
    except RuntimeError as error:
        raise CliError(str(error)) from error
    try:
        app = create_app(output_dir=output_dir, history_root=history_root)
    except (RuntimeError, OSError) as error:
        raise CliError(f"Could not start the Atlas web GUI: {error}") from error

    url = f"http://{host}:{port}"
    print("Atlas web UI running at:")
    print(url)
    (browser_opener or webbrowser.open)(url)
    run = server_runner or app.run
    # host is fixed to loopback; never bind to 0.0.0.0.
    run(host=host, port=port)
    return 0, ""


def atlas_history_command(
    *,
    history_root: str | Path = Path(".atlas") / "history",
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    profile_label: str | None = None
    if profile is not None:
        # The default history root is <base>/.atlas/history; the profile's
        # scoped history lives under the same base directory.
        scope = _resolve_profile_scope(
            profile, profile_service, Path(history_root).parent.parent
        )
        history_root = scope.history_root
        profile_label = scope.label
    index = HistoryRepository(history_root).load()
    return 0, render_atlas_history(
        index,
        profile_label=profile_label,
        history_display=Path(history_root).as_posix() if profile_label else None,
    )


def atlas_timeline_command(
    *,
    history_root: str | Path = Path(".atlas") / "history",
    output_path: str | Path = "timeline.md",
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    if profile is not None:
        scope = _resolve_profile_scope(
            profile, profile_service, Path(output_path).parent
        )
        history_root = scope.history_root
        output_path = _scoped_path(output_path, scope)
    repository = HistoryRepository(history_root)
    index = repository.load()
    try:
        markdown = generate_timeline(repository, index)
        destination = Path(output_path).resolve()
        destination.write_text(markdown, encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas timeline generation failed: {error}") from error
    return 0, render_atlas_timeline(index, str(destination))


def _save_history(
    history_root: str | Path,
    started_at: datetime,
    completed_at: datetime,
    report,
    graph,
    snapshot,
    brief,
    config_collections: tuple[tuple[str, str, str], ...] | None,
    destinations: dict[str, Path],
    *,
    profile_id: str | None = None,
    profile_name: str | None = None,
    credential_use: dict[str, str] | None = None,
) -> tuple[str, str | None]:
    """Best-effort preservation; never fails a successful discovery."""

    archive_names = (
        "topology_snapshot.json",
        "morning_brief.md",
        "atlas_topology.html",
        "change_report.json",
        "change_report.md",
        "config_change_report.json",
        "config_change_report.md",
        "state_change_report.json",
        "state_change_report.md",
        "intelligence_report.json",
        "intelligence_report.md",
        "root_cause_report.json",
        "root_cause_report.md",
    )
    artifacts = {
        name: destinations[name] for name in archive_names if name in destinations
    }
    # An incident report generated earlier in the day is evidence worth keeping.
    incident_report = destinations["snapshot"].parent / "incident_report.json"
    if incident_report.is_file():
        artifacts["incident_report.json"] = incident_report
    try:
        configuration_status, configured_count, config_directories = (
            _configuration_history(config_collections)
        )
        record = HistoryRepository(history_root).save_discovery(
            started_at=started_at.isoformat(timespec="seconds"),
            completed_at=completed_at.isoformat(timespec="seconds"),
            duration_seconds=max(0.0, (completed_at - started_at).total_seconds()),
            device_count=graph.summary()["device_count"],
            relationship_count=_logical_relationships(graph),
            warning_count=len(snapshot.warnings),
            failures=tuple(visit.host for visit in report.failed),
            configuration_status=configuration_status,
            configured_device_count=configured_count,
            quality_score=brief.evaluation.score,
            network_status=brief.brief.overall_status,
            snapshot_id=snapshot.snapshot_id,
            artifacts=artifacts,
            config_directories=config_directories,
            metadata={
                "atlas_version": VERSION_TEXT,
                # Provenance: which credential reference authenticated each
                # device this run. References only — never secrets.
                **(
                    {"credential_use": dict(credential_use)}
                    if credential_use
                    else {}
                ),
            },
            profile_id=profile_id,
            profile_name=profile_name,
        )
    except (OSError, TypeError, ValueError) as error:
        return f"History save failed: {error}", None
    directory = HistoryRepository(history_root).record_directory(record.record_id)
    return f"History saved: {directory}", record.record_id


def _configuration_history(
    config_collections: tuple[tuple[str, str, str], ...] | None,
) -> tuple[str, int, dict[str, Path]]:
    if config_collections is None:
        return CONFIG_NOT_REQUESTED, 0, {}
    directories = {
        hostname: Path(detail)
        for hostname, status, detail in config_collections
        if status != "failed"
    }
    statuses = [status for _, status, _ in config_collections]
    if statuses and all(status == "complete" for status in statuses):
        overall = CONFIG_COLLECTED
    elif any(status in ("complete", "partial") for status in statuses):
        overall = CONFIG_PARTIAL
    else:
        overall = CONFIG_FAILED
    return overall, len(directories), directories


def _logical_relationships(graph) -> int:
    hostname_by_id = {
        device.device_id: device.hostname for device in graph.devices()
    }
    links = {
        tuple(
            sorted(
                (
                    hostname_by_id.get(
                        edge.local_device_id, edge.local_device_id
                    ).casefold(),
                    edge.remote_hostname.casefold(),
                )
            )
        )
        for edge in graph.edges()
    }
    return len(links)


def atlas_dashboard_command(
    *,
    output_path: str | Path = "dashboard.html",
    snapshot_path: str | Path = "topology_snapshot.json",
    topology_path: str | Path = "atlas_topology.html",
    brief_path: str | Path = "morning_brief.md",
    change_report_json: str | Path = "change_report.json",
    change_report_md: str | Path = "change_report.md",
    configs_dir: str | Path = "configs",
    history_root: str | Path = Path(".atlas") / "history",
    timeline_path: str | Path = "timeline.md",
    config_change_report: str | Path = "config_change_report.json",
    config_change_report_md: str | Path = "config_change_report.md",
    state_change_report: str | Path = "state_change_report.json",
    state_change_report_md: str | Path = "state_change_report.md",
    incident_report: str | Path = "incident_report.json",
    incident_report_md: str | Path = "incident_report.md",
    intelligence_report: str | Path = "intelligence_report.json",
    intelligence_report_md: str | Path = "intelligence_report.md",
    root_cause_report: str | Path = "root_cause_report.json",
    root_cause_report_md: str | Path = "root_cause_report.md",
    browser_opener: BrowserOpener | None = None,
    profile: str | None = None,
    profile_service: ProfileService | None = None,
) -> tuple[int, str]:
    if profile is not None:
        scope = _resolve_profile_scope(
            profile, profile_service, Path(output_path).parent
        )
        output_path = _scoped_path(output_path, scope)
        snapshot_path = _scoped_path(snapshot_path, scope)
        topology_path = _scoped_path(topology_path, scope)
        brief_path = _scoped_path(brief_path, scope)
        change_report_json = _scoped_path(change_report_json, scope)
        change_report_md = _scoped_path(change_report_md, scope)
        configs_dir = scope.output_dir / Path(configs_dir).name
        history_root = scope.history_root
        timeline_path = _scoped_path(timeline_path, scope)
        config_change_report = _scoped_path(config_change_report, scope)
        config_change_report_md = _scoped_path(config_change_report_md, scope)
        state_change_report = _scoped_path(state_change_report, scope)
        state_change_report_md = _scoped_path(state_change_report_md, scope)
        incident_report = _scoped_path(incident_report, scope)
        incident_report_md = _scoped_path(incident_report_md, scope)
        intelligence_report = _scoped_path(intelligence_report, scope)
        intelligence_report_md = _scoped_path(intelligence_report_md, scope)
        root_cause_report = _scoped_path(root_cause_report, scope)
        root_cause_report_md = _scoped_path(root_cause_report_md, scope)
        scope.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        destination = Path(output_path).resolve()
        summary = build_dashboard_summary(
            snapshot_path=snapshot_path,
            topology_path=topology_path,
            brief_path=brief_path,
            change_report_json=change_report_json,
            change_report_md=change_report_md,
            configs_dir=configs_dir,
            history_root=history_root,
            timeline_path=timeline_path,
            config_change_report=config_change_report,
            config_change_report_md=config_change_report_md,
            state_change_report=state_change_report,
            state_change_report_md=state_change_report_md,
            incident_report=incident_report,
            incident_report_md=incident_report_md,
            intelligence_report=intelligence_report,
            intelligence_report_md=intelligence_report_md,
            root_cause_report=root_cause_report,
            root_cause_report_md=root_cause_report_md,
            link_base=destination.parent,
        )
        destination.write_text(DashboardRenderer(summary).render(), encoding="utf-8")
        opener = browser_opener or webbrowser.open
        opener(destination.as_uri())
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas dashboard generation failed: {error}") from error
    return 0, render_atlas_dashboard(summary, str(destination))


def _regenerate_dashboard(
    dashboard_output: str | Path,
    topology_destination: Path,
    snapshot_destination: Path,
    brief_destination: Path,
    config_output_dir: str | Path,
    history_root: str | Path,
) -> str:
    """Best-effort dashboard refresh; never fails a successful discovery."""

    destination = Path(dashboard_output).resolve()
    try:
        summary = build_dashboard_summary(
            snapshot_path=snapshot_destination,
            topology_path=topology_destination,
            brief_path=brief_destination,
            change_report_json=destination.parent / "change_report.json",
            change_report_md=destination.parent / "change_report.md",
            configs_dir=config_output_dir,
            history_root=history_root,
            timeline_path=destination.parent / "timeline.md",
            config_change_report=destination.parent / "config_change_report.json",
            config_change_report_md=destination.parent / "config_change_report.md",
            state_change_report=destination.parent / "state_change_report.json",
            state_change_report_md=destination.parent / "state_change_report.md",
            incident_report=destination.parent / "incident_report.json",
            incident_report_md=destination.parent / "incident_report.md",
            intelligence_report=destination.parent / "intelligence_report.json",
            intelligence_report_md=destination.parent / "intelligence_report.md",
            root_cause_report=destination.parent / "root_cause_report.json",
            root_cause_report_md=destination.parent / "root_cause_report.md",
            link_base=destination.parent,
        )
        destination.write_text(DashboardRenderer(summary).render(), encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        return f"Dashboard update failed: {error}"
    return f"Dashboard saved: {destination}"


def _collect_configurations_if_requested(
    read_input: PromptReader,
    build_transport: TransportFactory,
    credentials: DeviceCredentials,
    report,
    config_output_dir: str | Path,
    *,
    collect_override: bool | None = None,
    host_factory=None,
) -> tuple[tuple[str, str, str], ...] | None:
    """Collect read-only configuration per discovered device.

    ``collect_override`` (from a saved profile) skips the interactive prompt.
    ``host_factory`` (multi-credential runs) builds the per-host transport
    with the same safe credential resolution discovery used. Returns None
    when declined, else (hostname, status, detail) entries where detail is
    the artifact directory or a clean failure message.
    """

    if collect_override is not None:
        collect = collect_override
    else:
        try:
            answer = read_input("Collect running configuration? [y/N] ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        collect = answer in ("y", "yes")
    if not collect:
        return None
    collections: list[tuple[str, str, str]] = []
    for visit, result in zip(report.connected, report.results):
        hostname = result.device.hostname
        try:
            if host_factory is not None:
                transport = host_factory(visit.host)
            else:
                transport = build_transport(replace(credentials, host=visit.host))
            artifact = collect_configuration(transport, result)
            paths = write_configuration_artifacts(
                artifact,
                Path(config_output_dir) / safe_artifact_name(hostname),
            )
            collections.append((hostname, artifact.status, str(paths.directory)))
        except (AtlasConfigurationError, AtlasTransportError, OSError) as error:
            collections.append((hostname, "failed", str(error)))
    return tuple(collections)


def atlas_compare_command(
    previous_path: str | Path,
    current_path: str | Path,
    *,
    json_output: str | Path = "change_report.json",
    markdown_output: str | Path = "change_report.md",
) -> tuple[int, str]:
    previous = _load_snapshot_file(previous_path)
    current = _load_snapshot_file(current_path)
    try:
        report = ChangeDetector().compare(previous, current)
        json_destination = Path(json_output).resolve()
        json_destination.write_text(render_change_report_json(report), encoding="utf-8")
        markdown_destination = Path(markdown_output).resolve()
        markdown_destination.write_text(
            render_change_report_markdown(report), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas snapshot comparison failed: {error}") from error
    return 0, render_atlas_compare(
        report, str(json_destination), str(markdown_destination)
    )


def _load_snapshot_file(path: str | Path) -> dict:
    resolved = Path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise CliError(f"Could not read snapshot file {resolved}: {error}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise CliError(f"{resolved} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise CliError(f"{resolved} does not contain a topology snapshot object")
    return data


def _read_limit(read_input: PromptReader, prompt: str, default: int) -> int:
    try:
        text = read_input(prompt).strip()
    except (EOFError, KeyboardInterrupt) as error:
        raise CliError("Discovery was cancelled before connecting to a device") from error
    if not text:
        return default
    try:
        return int(text)
    except ValueError as error:
        raise CliError(f"{prompt.split(' [')[0]} must be a whole number") from error


def atlas_morning_brief_command(
    discovery_runner: AtlasDiscoveryRunner = run_atlas_discovery_demo,
    *,
    journey_runner: MorningBriefRunner | None = None,
    output_path: str | Path = "morning_brief.md",
) -> tuple[int, str]:
    try:
        discovery, _, current = discovery_runner()
        previous_graph = TopologyGraph()
        previous_graph.merge_discovery_result(discovery)
        previous = TopologySnapshot.from_graph(
            previous_graph,
            metadata={"source": "atlas_morning_brief_baseline"},
        )
        run = journey_runner or MorningBriefJourney().run
        outcome = run(current, previous)
        if not isinstance(outcome, MorningBriefJourneyResult):
            raise TypeError("Atlas Morning Brief returned an invalid result")
        destination = Path(output_path).resolve()
        destination.write_text(outcome.markdown, encoding="utf-8")
    except (AtlasDiscoveryError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise CliError(f"Atlas Morning Brief failed: {error}") from error
    return 0, render_atlas_morning_brief(outcome, str(destination))
