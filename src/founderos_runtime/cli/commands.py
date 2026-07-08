"""Thin public commands over existing FounderOS runtime components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import getpass
from pathlib import Path
import webbrowser

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
    render_atlas_discover,
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
    browser_opener: BrowserOpener | None = None,
) -> tuple[int, str]:
    read_input = input_reader or input
    read_password = password_reader or getpass.getpass
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
    return 0, render_atlas_discover(
        report,
        graph,
        snapshot,
        brief,
        str(topology_destination),
        str(snapshot_destination),
        str(brief_destination),
    )


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
