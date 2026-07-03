"""Thin public commands over existing FounderOS runtime components."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import webbrowser

from founderos_atlas.demo import run_atlas_discovery_demo
from founderos_atlas.discovery import AtlasDiscoveryError, DiscoveryResult
from founderos_atlas.journeys import MorningBriefJourney, MorningBriefJourneyResult
from founderos_atlas.topology import TopologyGraph, TopologySnapshot
from founderos_atlas.visualization import TopologyRenderer
from founderos_runtime.demo import load_discovery_workspace, run_discovery_vertical_slice
from founderos_runtime.evaluation import EvaluationRunner
from founderos_runtime.journey import JourneyResult, JourneyStatus
from founderos_runtime.provider import MockProvider
from founderos_runtime.workspace import WorkspaceError

from .exceptions import CliError
from .render import (
    VERSION_TEXT,
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
