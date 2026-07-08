"""Deterministic plain-text rendering for public CLI commands."""

from __future__ import annotations

from collections.abc import Mapping

from founderos_atlas.discovery import DiscoveryResult
from founderos_atlas.journeys import MorningBriefJourneyResult
from founderos_atlas.topology import TopologyGraph, TopologySnapshot
from founderos_runtime.journey import JourneyResult


VERSION_TEXT = "FounderOS v0.3 Alpha"


def render_help() -> str:
    return "\n".join(
        (
            VERSION_TEXT,
            "",
            "Usage:",
            "  founderos version",
            "  founderos doctor",
            "  founderos demo discovery",
            "  founderos atlas demo discovery",
            "  founderos atlas demo topology",
            "  founderos atlas morning-brief",
            "  founderos atlas discover",
            "  founderos help",
            "",
            "Commands:",
            "  version         Show the FounderOS Alpha version.",
            "  doctor          Check deterministic demo dependencies.",
            "  demo discovery  Run the in-memory Discovery vertical slice.",
            "  atlas demo discovery  Run fixture-only Atlas network discovery.",
            "  atlas demo topology  Generate and open the Atlas topology viewer.",
            "  atlas morning-brief  Generate an evaluated Atlas operational brief.",
            "  atlas discover  Discover a live Cisco IOS/IOS-XE device over read-only SSH.",
            "  help            Show this help.",
        )
    )


def render_doctor(checks: Mapping[str, bool]) -> str:
    lines = ["FounderOS Doctor", ""]
    for name in ("runtime", "manifests", "evaluation", "provider"):
        lines.append(f"{name.capitalize()}: {'PASS' if checks.get(name) else 'FAIL'}")
    lines.extend(("", f"Overall: {'PASS' if all(checks.values()) else 'FAIL'}"))
    return "\n".join(lines)


def render_discovery(result: JourneyResult) -> str:
    evaluations = result.evaluation_results
    score = evaluations[0].score if evaluations else 0.0
    artifact_names = sorted(result.generated_artifacts)
    validation = result.metadata.get("validation", {})
    authorization = result.metadata.get("authorization", {})
    validation_text = "passed" if validation.get("valid") else "failed"
    authorization_text = "granted" if authorization.get("allowed") else "denied"
    artifacts_text = ", ".join(artifact_names) if artifact_names else "None"
    return "\n".join(
        (
            "Loading workspace...",
            "Planning journey...",
            f"Validation {validation_text}.",
            f"Authorization {authorization_text}.",
            "Running journey...",
            "Evaluating artifacts...",
            f"Opportunity Report Score: {score:.2f}",
            "Journey completed." if result.status.value == "succeeded" else "Journey failed.",
            "",
            f"Artifacts generated: {artifacts_text}",
            f"Evaluation score: {score:.2f}",
            f"Journey status: {result.status.value}",
            "Execution duration: not recorded (deterministic in-memory demo)",
        )
    )


def render_error(message: str) -> str:
    return f"Error: {message}"


def render_atlas_topology(path: str) -> str:
    return "\n".join(
        (
            "Atlas Topology Viewer",
            "",
            f"HTML generated: {path}",
            "Browser launch requested.",
        )
    )


def render_atlas_morning_brief(result: MorningBriefJourneyResult, path: str) -> str:
    brief = result.brief
    return "\n".join(
        (
            "Atlas Morning Brief",
            "",
            f"Network status: {brief.overall_status}",
            f"Devices: {brief.device_count}",
            f"Connections: {brief.edge_count}",
            f"New devices: {len(brief.new_devices)}",
            f"Removed devices: {len(brief.removed_devices)}",
            f"Changed devices: {len(brief.changed_devices)}",
            f"Warnings: {len(brief.warnings)}",
            f"Quality score: {result.evaluation.score:.2f}",
            f"Journey status: {result.journey_result.status.value}",
            "",
            f"Artifact saved: {path}",
        )
    )


def render_atlas_discover(
    result: DiscoveryResult,
    graph: TopologyGraph,
    snapshot: TopologySnapshot,
    brief_result: MorningBriefJourneyResult,
    topology_path: str,
    brief_path: str,
) -> str:
    device = result.device
    summary = graph.summary()
    brief = brief_result.brief
    return "\n".join(
        (
            "=" * 48,
            "Atlas Live Discovery",
            "=" * 48,
            "",
            f"Device: {device.hostname} ({device.management_ip})",
            f"Vendor: {device.vendor.title()}",
            f"Platform: {device.platform}",
            f"Operating system: {device.os_name} {device.os_version}",
            f"Interfaces: {len(result.interfaces)}",
            f"Neighbors: {len(result.neighbors)}",
            "",
            "Topology",
            f"Devices: {summary['device_count']}",
            f"Edges: {summary['edge_count']}",
            f"Warnings: {summary['warning_count']}",
            "",
            "Topology Snapshot",
            f"Snapshot ID: {snapshot.snapshot_id}",
            f"Schema version: {snapshot.metadata['schema_version']}",
            "",
            "Morning Brief",
            f"Network status: {brief.overall_status}",
            f"Quality score: {brief_result.evaluation.score:.2f}",
            "",
            f"Topology viewer saved: {topology_path}",
            f"Morning brief saved: {brief_path}",
            "Browser launch requested.",
            "",
            "Live discovery completed successfully.",
            "=" * 48,
        )
    )


def render_atlas_discovery(
    result: DiscoveryResult,
    graph: TopologyGraph,
    snapshot: TopologySnapshot,
) -> str:
    device = result.device
    neighbors = tuple(
        sorted(
            graph.neighbors(device.device_id),
            key=lambda item: (
                item.remote_hostname.casefold(),
                (item.remote_interface or "").casefold(),
            ),
        )
    )
    tree_lines = [device.hostname]
    for index, neighbor in enumerate(neighbors):
        branch = "`--" if index == len(neighbors) - 1 else "|--"
        tree_lines.append(f" {branch} {neighbor.remote_hostname}")
    summary = graph.summary()
    return "\n".join(
        (
            "=" * 48,
            "Atlas Discovery Demo",
            "=" * 48,
            "",
            "Loading Cisco IOS fixtures...",
            "Device discovered.",
            "",
            f"Hostname: {device.hostname}",
            f"Vendor: {device.vendor.title()}",
            f"Platform: {device.platform}",
            f"Operating system: {device.os_name} {device.os_version}",
            f"Interfaces: {len(result.interfaces)}",
            f"Neighbors: {len(result.neighbors)}",
            "",
            "Building topology...",
            "",
            "Before reconciliation",
            f"Devices: {summary['input_device_count']}",
            "",
            "After reconciliation",
            f"Devices: {summary['device_count']}",
            f"Duplicates removed: {summary['duplicates_removed']}",
            f"Warnings: {summary['warning_count']}",
            "",
            "Topology",
            *tree_lines,
            "",
            "Summary",
            f"Devices: {summary['device_count']}",
            f"Edges: {summary['edge_count']}",
            "",
            "Topology Snapshot",
            f"Snapshot ID: {snapshot.snapshot_id}",
            f"Devices: {snapshot.device_count}",
            f"Edges: {snapshot.edge_count}",
            f"Warnings: {len(snapshot.warnings)}",
            f"Schema version: {snapshot.metadata['schema_version']}",
            "",
            "Discovery completed successfully.",
            "=" * 48,
        )
    )
