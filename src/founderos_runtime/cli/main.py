"""Public command routing for FounderOS v0.3 Alpha."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys

from founderos_atlas.demo import run_atlas_discovery_demo
from founderos_runtime.demo import run_discovery_vertical_slice

from . import legacy
from .commands import (
    AtlasDiscoveryRunner,
    BrowserOpener,
    DiscoveryRunner,
    MorningBriefRunner,
    PromptReader,
    TransportFactory,
    atlas_compare_command,
    atlas_dashboard_command,
    atlas_discover_command,
    atlas_discovery_command,
    atlas_morning_brief_command,
    atlas_topology_command,
    discovery_command,
    doctor_command,
    help_command,
    version_command,
)
from .exceptions import CliError
from .render import render_error


_PUBLIC_COMMANDS = {"version", "doctor", "demo", "atlas", "help", "-h", "--help"}
_LEGACY_COMMANDS = {
    "new", "status", "plan", "founder-brief", "approve", "decisions", "events",
    "health", "recover", "audit", "runs", "transitions", "discovery",
    "approve-opportunity",
}


def main(
    argv: Sequence[str] | None = None,
    *,
    discovery_runner: DiscoveryRunner = run_discovery_vertical_slice,
    atlas_discovery_runner: AtlasDiscoveryRunner = run_atlas_discovery_demo,
    atlas_topology_output: str | Path = "atlas_topology.html",
    atlas_browser_opener: BrowserOpener | None = None,
    atlas_morning_brief_runner: MorningBriefRunner | None = None,
    atlas_morning_brief_output: str | Path = "morning_brief.md",
    atlas_transport_factory: TransportFactory | None = None,
    atlas_input_reader: PromptReader | None = None,
    atlas_password_reader: PromptReader | None = None,
    atlas_snapshot_output: str | Path = "topology_snapshot.json",
    atlas_compare_json_output: str | Path = "change_report.json",
    atlas_compare_markdown_output: str | Path = "change_report.md",
    atlas_config_output_dir: str | Path = "configs",
    atlas_dashboard_output: str | Path = "dashboard.html",
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        code, output = help_command()
    elif arguments[0] == "--project-dir" or arguments[0] in _LEGACY_COMMANDS:
        return legacy.main(arguments)
    elif arguments in (["help"], ["-h"], ["--help"]):
        code, output = help_command()
    elif arguments == ["version"]:
        code, output = version_command()
    elif arguments == ["doctor"]:
        code, output = doctor_command()
    elif arguments == ["demo", "discovery"]:
        try:
            code, output = discovery_command(discovery_runner)
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments == ["atlas", "demo", "discovery"]:
        try:
            code, output = atlas_discovery_command(atlas_discovery_runner)
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments == ["atlas", "demo", "topology"]:
        try:
            code, output = atlas_topology_command(
                atlas_discovery_runner,
                output_path=atlas_topology_output,
                browser_opener=atlas_browser_opener,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments == ["atlas", "discover"]:
        try:
            code, output = atlas_discover_command(
                transport_factory=atlas_transport_factory,
                input_reader=atlas_input_reader,
                password_reader=atlas_password_reader,
                journey_runner=atlas_morning_brief_runner,
                topology_output=atlas_topology_output,
                snapshot_output=atlas_snapshot_output,
                brief_output=atlas_morning_brief_output,
                config_output_dir=atlas_config_output_dir,
                dashboard_output=atlas_dashboard_output,
                browser_opener=atlas_browser_opener,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments == ["atlas", "dashboard"]:
        try:
            code, output = atlas_dashboard_command(
                output_path=atlas_dashboard_output,
                snapshot_path=atlas_snapshot_output,
                topology_path=atlas_topology_output,
                brief_path=atlas_morning_brief_output,
                change_report_json=atlas_compare_json_output,
                change_report_md=atlas_compare_markdown_output,
                configs_dir=atlas_config_output_dir,
                browser_opener=atlas_browser_opener,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "compare"]:
        if len(arguments) != 4:
            print(
                render_error("Usage: founderos atlas compare <previous.json> <current.json>"),
                file=sys.stderr,
            )
            return 2
        try:
            code, output = atlas_compare_command(
                arguments[2],
                arguments[3],
                json_output=atlas_compare_json_output,
                markdown_output=atlas_compare_markdown_output,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments == ["atlas", "morning-brief"]:
        try:
            code, output = atlas_morning_brief_command(
                atlas_discovery_runner,
                journey_runner=atlas_morning_brief_runner,
                output_path=atlas_morning_brief_output,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    else:
        print(render_error(f"Unknown command: {' '.join(arguments)}"), file=sys.stderr)
        return 2
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
