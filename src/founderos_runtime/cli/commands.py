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
    clock: Clock | None = None,
    browser_opener: BrowserOpener | None = None,
) -> tuple[int, str]:
    read_input = input_reader or input
    read_password = password_reader or getpass.getpass
    read_clock = clock or (lambda: datetime.now(timezone.utc))
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
    started_at = read_clock()
    try:
        config = MultiHopConfig(max_depth=max_depth, max_devices=max_devices)
        credentials = DeviceCredentials(host=host, username=username, password=password)
        build_transport = transport_factory or SSHDeviceTransport

        def host_transport(next_host: str) -> DeviceTransport:
            return build_transport(replace(credentials, host=next_host))

        report, graph, snapshot = run_multihop_discovery(
            host_transport, credentials.host, config=config
        )
        html = TopologyRenderer(snapshot).render()
        topology_destination = Path(topology_output).resolve()
        topology_destination.write_text(html, encoding="utf-8")
        snapshot_destination = Path(snapshot_output).resolve()
        snapshot_destination.write_text(
            TopologySnapshotExporter(snapshot).to_json() + "\n", encoding="utf-8"
        )
        run_brief = journey_runner or MorningBriefJourney().run
        brief = run_brief(snapshot, None)
        if not isinstance(brief, MorningBriefJourneyResult):
            raise TypeError("Atlas Morning Brief returned an invalid result")
        brief_destination = Path(brief_output).resolve()
        brief_destination.write_text(brief.markdown, encoding="utf-8")
        opener = browser_opener or webbrowser.open
        opener(topology_destination.as_uri())
    except AtlasTransportError as error:
        raise CliError(str(error)) from error
    except (AtlasDiscoveryError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise CliError(f"Atlas live discovery failed: {error}") from error
    config_collections = _collect_configurations_if_requested(
        read_input,
        build_transport,
        credentials,
        report,
        config_output_dir,
    )
    completed_at = read_clock()
    history_line, record_id = _save_history(
        history_root,
        started_at,
        completed_at,
        report,
        graph,
        snapshot,
        brief,
        config_collections,
        topology_destination,
        snapshot_destination,
        brief_destination,
    )
    dashboard_line = _regenerate_dashboard(
        dashboard_output,
        topology_destination,
        snapshot_destination,
        brief_destination,
        config_output_dir,
        history_root,
    )
    if record_id is not None:
        HistoryRepository(history_root).attach_artifact(
            record_id, Path(dashboard_output).resolve()
        )
    return 0, render_atlas_discover(
        report,
        graph,
        snapshot,
        brief,
        str(topology_destination),
        str(snapshot_destination),
        str(brief_destination),
        config_collections=config_collections,
        dashboard_line=dashboard_line,
        history_line=history_line,
    )


def atlas_config_diff_command(
    previous_path: str | Path | None = None,
    current_path: str | Path | None = None,
    *,
    latest_hostname: str | None = None,
    history_root: str | Path = Path(".atlas") / "history",
    json_output: str | Path = "config_change_report.json",
    markdown_output: str | Path = "config_change_report.md",
) -> tuple[int, str]:
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
) -> tuple[int, str]:
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
        markdown_destination.write_text(
            render_incident_report_markdown(report), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as error:
        raise CliError(f"Atlas incident investigation failed: {error}") from error
    return 0, render_atlas_investigate(
        report, str(json_destination), str(markdown_destination)
    )


def atlas_history_command(
    *, history_root: str | Path = Path(".atlas") / "history"
) -> tuple[int, str]:
    index = HistoryRepository(history_root).load()
    return 0, render_atlas_history(index)


def atlas_timeline_command(
    *,
    history_root: str | Path = Path(".atlas") / "history",
    output_path: str | Path = "timeline.md",
) -> tuple[int, str]:
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
    topology_destination: Path,
    snapshot_destination: Path,
    brief_destination: Path,
) -> tuple[str, str | None]:
    """Best-effort preservation; never fails a successful discovery."""

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
            artifacts={
                "topology_snapshot.json": snapshot_destination,
                "morning_brief.md": brief_destination,
                "atlas_topology.html": topology_destination,
            },
            config_directories=config_directories,
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
    incident_report: str | Path = "incident_report.json",
    incident_report_md: str | Path = "incident_report.md",
    browser_opener: BrowserOpener | None = None,
) -> tuple[int, str]:
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
            incident_report=incident_report,
            incident_report_md=incident_report_md,
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
            incident_report=destination.parent / "incident_report.json",
            incident_report_md=destination.parent / "incident_report.md",
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
) -> tuple[tuple[str, str, str], ...] | None:
    """Ask once, then collect read-only configuration per discovered device.

    Returns None when declined, else (hostname, status, detail) entries where
    detail is the artifact directory or a clean failure message.
    """

    try:
        answer = read_input("Collect running configuration? [y/N] ").strip().casefold()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        return None
    collections: list[tuple[str, str, str]] = []
    for visit, result in zip(report.connected, report.results):
        hostname = result.device.hostname
        try:
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
