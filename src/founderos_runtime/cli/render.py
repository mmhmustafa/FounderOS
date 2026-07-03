"""Deterministic plain-text rendering for public CLI commands."""

from __future__ import annotations

from collections.abc import Mapping

from founderos_atlas.discovery import DiscoveryResult
from founderos_atlas.topology import TopologyGraph
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
            "  founderos help",
            "",
            "Commands:",
            "  version         Show the FounderOS Alpha version.",
            "  doctor          Check deterministic demo dependencies.",
            "  demo discovery  Run the in-memory Discovery vertical slice.",
            "  atlas demo discovery  Run fixture-only Atlas network discovery.",
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


def render_atlas_discovery(result: DiscoveryResult, graph: TopologyGraph) -> str:
    device = result.device
    neighbors = graph.neighbors(device.device_id)
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
            "Topology",
            *tree_lines,
            "",
            "Summary",
            f"Devices: {summary['device_count']}",
            f"Edges: {summary['edge_count']}",
            "",
            "Discovery completed successfully.",
            "=" * 48,
        )
    )
