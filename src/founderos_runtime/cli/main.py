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
    atlas_config_diff_command,
    atlas_state_diff_command,
    atlas_dashboard_command,
    atlas_discover_command,
    atlas_history_command,
    atlas_investigate_command,
    atlas_profile_add_command,
    atlas_profile_delete_command,
    atlas_profile_list_command,
    atlas_profile_show_command,
    atlas_profile_update_command,
    atlas_timeline_command,
    atlas_web_command,
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
    atlas_history_root: str | Path = Path(".atlas") / "history",
    atlas_timeline_output: str | Path = "timeline.md",
    atlas_clock=None,
    atlas_config_diff_json_output: str | Path = "config_change_report.json",
    atlas_config_diff_markdown_output: str | Path = "config_change_report.md",
    atlas_incident_json_output: str | Path = "incident_report.json",
    atlas_incident_markdown_output: str | Path = "incident_report.md",
    atlas_state_diff_json_output: str | Path = "state_change_report.json",
    atlas_state_diff_markdown_output: str | Path = "state_change_report.md",
    atlas_intelligence_json_output: str | Path | None = None,
    atlas_intelligence_markdown_output: str | Path | None = None,
    atlas_root_cause_json_output: str | Path | None = None,
    atlas_root_cause_markdown_output: str | Path | None = None,
    atlas_profile_service=None,
    atlas_web_server_runner=None,
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
    elif arguments[:2] == ["atlas", "discover"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        if remaining:
            print(
                render_error(
                    "Usage: founderos atlas discover [--profile <name>]"
                ),
                file=sys.stderr,
            )
            return 2
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
                history_root=atlas_history_root,
                change_report_json_output=atlas_compare_json_output,
                change_report_markdown_output=atlas_compare_markdown_output,
                config_change_json_output=atlas_config_diff_json_output,
                config_change_markdown_output=atlas_config_diff_markdown_output,
                state_change_json_output=atlas_state_diff_json_output,
                state_change_markdown_output=atlas_state_diff_markdown_output,
                intelligence_json_output=atlas_intelligence_json_output,
                intelligence_markdown_output=atlas_intelligence_markdown_output,
                root_cause_json_output=atlas_root_cause_json_output,
                root_cause_markdown_output=atlas_root_cause_markdown_output,
                clock=atlas_clock,
                browser_opener=atlas_browser_opener,
                profile=profile_name,
                profile_service=atlas_profile_service,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "profile"]:
        result = _run_profile_command(
            arguments[2:],
            service=atlas_profile_service,
            input_reader=atlas_input_reader,
            password_reader=atlas_password_reader,
        )
        if result is None:
            return 2
        try:
            code, output = result()
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "config-diff"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        try:
            if len(remaining) == 2 and remaining[0] == "--latest":
                code, output = atlas_config_diff_command(
                    latest_hostname=remaining[1],
                    history_root=atlas_history_root,
                    json_output=atlas_config_diff_json_output,
                    markdown_output=atlas_config_diff_markdown_output,
                    profile=profile_name,
                    profile_service=atlas_profile_service,
                )
            elif len(remaining) == 2:
                code, output = atlas_config_diff_command(
                    remaining[0],
                    remaining[1],
                    json_output=atlas_config_diff_json_output,
                    markdown_output=atlas_config_diff_markdown_output,
                    profile=profile_name,
                    profile_service=atlas_profile_service,
                )
            else:
                print(
                    render_error(
                        "Usage: founderos atlas config-diff <previous> <current> "
                        "| founderos atlas config-diff --latest <hostname>"
                    ),
                    file=sys.stderr,
                )
                return 2
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "state-diff"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        try:
            if remaining == ["--latest"]:
                code, output = atlas_state_diff_command(
                    latest=True,
                    history_root=atlas_history_root,
                    json_output=atlas_state_diff_json_output,
                    markdown_output=atlas_state_diff_markdown_output,
                    profile=profile_name,
                    profile_service=atlas_profile_service,
                )
            elif len(remaining) == 2:
                code, output = atlas_state_diff_command(
                    remaining[0],
                    remaining[1],
                    json_output=atlas_state_diff_json_output,
                    markdown_output=atlas_state_diff_markdown_output,
                    profile=profile_name,
                    profile_service=atlas_profile_service,
                )
            else:
                print(
                    render_error(
                        "Usage: founderos atlas state-diff <previous.json> <current.json> "
                        "| founderos atlas state-diff --latest"
                    ),
                    file=sys.stderr,
                )
                return 2
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "investigate"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        if remaining:
            print(
                render_error("Usage: founderos atlas investigate [--profile <name>]"),
                file=sys.stderr,
            )
            return 2
        try:
            code, output = atlas_investigate_command(
                input_reader=atlas_input_reader,
                clock=atlas_clock,
                snapshot_path=atlas_snapshot_output,
                change_report_json=atlas_compare_json_output,
                config_change_report=atlas_config_diff_json_output,
                brief_path=atlas_morning_brief_output,
                configs_dir=atlas_config_output_dir,
                history_root=atlas_history_root,
                json_output=atlas_incident_json_output,
                markdown_output=atlas_incident_markdown_output,
                profile=profile_name,
                profile_service=atlas_profile_service,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments == ["atlas", "web"]:
        try:
            code, output = atlas_web_command(
                history_root=atlas_history_root,
                browser_opener=atlas_browser_opener,
                server_runner=atlas_web_server_runner,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "history"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        if remaining:
            print(
                render_error("Usage: founderos atlas history [--profile <name>]"),
                file=sys.stderr,
            )
            return 2
        try:
            code, output = atlas_history_command(
                history_root=atlas_history_root,
                profile=profile_name,
                profile_service=atlas_profile_service,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "timeline"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        if remaining:
            print(
                render_error("Usage: founderos atlas timeline [--profile <name>]"),
                file=sys.stderr,
            )
            return 2
        try:
            code, output = atlas_timeline_command(
                history_root=atlas_history_root,
                output_path=atlas_timeline_output,
                profile=profile_name,
                profile_service=atlas_profile_service,
            )
        except CliError as error:
            print(render_error(str(error)), file=sys.stderr)
            return 1
    elif arguments[:2] == ["atlas", "dashboard"]:
        profile_name, remaining = _parse_profile_flag(arguments[2:])
        if remaining:
            print(
                render_error("Usage: founderos atlas dashboard [--profile <name>]"),
                file=sys.stderr,
            )
            return 2
        try:
            code, output = atlas_dashboard_command(
                output_path=atlas_dashboard_output,
                snapshot_path=atlas_snapshot_output,
                topology_path=atlas_topology_output,
                brief_path=atlas_morning_brief_output,
                change_report_json=atlas_compare_json_output,
                change_report_md=atlas_compare_markdown_output,
                configs_dir=atlas_config_output_dir,
                history_root=atlas_history_root,
                timeline_path=atlas_timeline_output,
                config_change_report=atlas_config_diff_json_output,
                config_change_report_md=atlas_config_diff_markdown_output,
                state_change_report=atlas_state_diff_json_output,
                state_change_report_md=atlas_state_diff_markdown_output,
                incident_report=atlas_incident_json_output,
                incident_report_md=atlas_incident_markdown_output,
                browser_opener=atlas_browser_opener,
                profile=profile_name,
                profile_service=atlas_profile_service,
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


def _parse_profile_flag(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Extract --profile <name> / --profile=<name>; return (name, leftover)."""

    remaining: list[str] = []
    profile: str | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--profile" and index + 1 < len(tokens):
            profile = tokens[index + 1]
            index += 2
            continue
        if token.startswith("--profile="):
            profile = token.split("=", 1)[1]
            index += 1
            continue
        remaining.append(token)
        index += 1
    return profile, remaining


def _run_profile_command(tokens, *, service, input_reader, password_reader):
    """Return a zero-arg callable producing (code, output), or None on misuse."""

    if not tokens:
        print(
            render_error(
                "Usage: founderos atlas profile add | list | show <name> | "
                "update <name> | delete <name>"
            ),
            file=sys.stderr,
        )
        return None
    action, rest = tokens[0], tokens[1:]
    if action == "add" and not rest:
        return lambda: atlas_profile_add_command(
            input_reader=input_reader,
            password_reader=password_reader,
            service=service,
        )
    if action == "list" and not rest:
        return lambda: atlas_profile_list_command(service=service)
    if action == "show" and len(rest) == 1:
        return lambda: atlas_profile_show_command(rest[0], service=service)
    if action == "update" and len(rest) == 1:
        return lambda: atlas_profile_update_command(
            rest[0],
            input_reader=input_reader,
            password_reader=password_reader,
            service=service,
        )
    if action == "delete" and len(rest) == 1:
        return lambda: atlas_profile_delete_command(rest[0], service=service)
    print(
        render_error(
            "Usage: founderos atlas profile add | list | show <name> | "
            "update <name> | delete <name>"
        ),
        file=sys.stderr,
    )
    return None


if __name__ == "__main__":
    raise SystemExit(main())
