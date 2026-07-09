"""Deterministic Atlas Morning Brief composed through FounderOS JourneyRunner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from founderos_runtime.evaluation import EvaluationResult, load_evaluation_rubric
from founderos_runtime.journey import JourneyResult, JourneyRunner, JourneyStatus
from founderos_runtime.workspace import Workspace

from founderos_atlas.change import ChangeDetector
from founderos_atlas.demo import atlas_app_root
from founderos_atlas.state import OperationalStateDetector
from founderos_atlas.topology import TopologySnapshot

from .artifacts import MorningBrief


MORNING_BRIEF_WORKFLOW_ID = "wfl_01ARZ3NDEKTSV4RRFFQ69G5FBY"


@dataclass(frozen=True)
class MorningBriefJourneyResult:
    brief: MorningBrief
    markdown: str
    evaluation: EvaluationResult
    journey_result: JourneyResult


class MorningBriefJourney:
    """Run the Atlas domain computation through FounderOS Journey infrastructure."""

    def __init__(self, app_root: str | Path | None = None) -> None:
        self._app_root = Path(app_root) if app_root is not None else atlas_app_root()

    def run(
        self,
        current_snapshot: TopologySnapshot,
        previous_snapshot: TopologySnapshot | None = None,
        *,
        generated_at: str | None = None,
        run_context: Mapping[str, Any] | None = None,
    ) -> MorningBriefJourneyResult:
        if not isinstance(current_snapshot, TopologySnapshot):
            raise TypeError("current_snapshot must be a TopologySnapshot")
        if previous_snapshot is not None and not isinstance(previous_snapshot, TopologySnapshot):
            raise TypeError("previous_snapshot must be a TopologySnapshot or None")

        workspace = Workspace.load(self._app_root, runtime_version="0.3.0")
        rubric_path = self._app_root / "manifests" / "rubrics" / "morning-brief-rubric.yaml"
        rubric = load_evaluation_rubric(rubric_path)

        def build_artifact(step: Any, inputs: Any) -> dict[str, Any]:
            if "topology_snapshots" not in inputs:
                raise ValueError("Morning Brief requires topology_snapshots")
            brief = build_morning_brief(
                current_snapshot,
                previous_snapshot,
                generated_at=generated_at,
                run_context=run_context,
            )
            return {"morning_brief": brief.to_dict()}

        runner = JourneyRunner(
            workspace,
            artifact_builders={"generate_morning_brief": build_artifact},
            rubric_resolver=lambda declaration: (
                rubric if declaration.get("id") == "morning_brief_quality" else None
            ),
        )
        snapshots = {
            "current": current_snapshot.to_dict(),
            "previous": previous_snapshot.to_dict() if previous_snapshot is not None else None,
        }
        result = runner.run(
            MORNING_BRIEF_WORKFLOW_ID,
            input_artifacts={"topology_snapshots": snapshots},
        )
        if result.status is not JourneyStatus.SUCCEEDED:
            raise RuntimeError("Morning Brief Journey did not complete successfully")
        if len(result.evaluation_results) != 1:
            raise RuntimeError("Morning Brief Journey must produce exactly one Evaluation")
        brief = MorningBrief.from_dict(result.generated_artifacts["morning_brief"])
        return MorningBriefJourneyResult(
            brief=brief,
            markdown=brief.to_markdown(),
            evaluation=result.evaluation_results[0],
            journey_result=result,
        )


def build_morning_brief(
    current: TopologySnapshot,
    previous: TopologySnapshot | None = None,
    *,
    generated_at: str | None = None,
    run_context: Mapping[str, Any] | None = None,
) -> MorningBrief:
    current_devices = _devices_by_hostname(current)
    previous_devices = _devices_by_hostname(previous) if previous is not None else {}
    current_names = set(current_devices)
    previous_names = set(previous_devices)
    new_keys = current_names - previous_names if previous is not None else set()
    removed_keys = previous_names - current_names
    changed_keys = {
        key
        for key in current_names & previous_names
        if _canonical(current_devices[key]) != _canonical(previous_devices[key])
    }
    if previous is not None:
        current_edges = {_canonical(edge) for edge in current.to_dict()["edges"]}
        previous_edges = {_canonical(edge) for edge in previous.to_dict()["edges"]}
        changed_edge_ids = current_edges ^ previous_edges
        if changed_edge_ids:
            changed_local_ids = {
                edge["local_device_id"]
                for edge in current.to_dict()["edges"] + previous.to_dict()["edges"]
                if _canonical(edge) in changed_edge_ids
            }
            for key, device in current_devices.items():
                if device["device_id"] in changed_local_ids:
                    changed_keys.add(key)
    new_devices = tuple(current_devices[key]["hostname"] for key in sorted(new_keys))
    removed_devices = tuple(previous_devices[key]["hostname"] for key in sorted(removed_keys))
    changed_devices = tuple(current_devices[key]["hostname"] for key in sorted(changed_keys))
    warnings = tuple(current.to_dict()["warnings"])
    conflicts = tuple(
        warning for warning in warnings if "conflict" in str(warning.get("code", ""))
    )
    recommendations = _recommendations(
        removed_devices, changed_devices, warnings, conflicts
    )
    change_report = None
    state_report = None
    if previous is not None:
        change_report = ChangeDetector().compare(previous, current)
        recommendations = recommendations + tuple(
            item for item in change_report.recommendations if item not in recommendations
        )
        state_report = OperationalStateDetector().compare(previous, current)
        # Only unresolved (active) issues drive recommendations and status; a
        # recovery is reported as history but must not keep status in Warning.
        recommendations = recommendations + tuple(
            change.recommendation
            for change in state_report.active_issues
            if change.recommendation not in recommendations
        )
    operational_active = (
        state_report.active_issue_count if state_report is not None else 0
    )
    status = (
        "Attention Required"
        if removed_devices or changed_devices or warnings or operational_active
        else "Healthy"
    )
    baseline = "No comparison baseline was supplied." if previous is None else (
        f"Detected {len(new_devices)} new, {len(removed_devices)} removed, and "
        f"{len(changed_devices)} changed devices."
    )
    summary = (
        f"Atlas observed {current.device_count} devices and {current.edge_count} connections. "
        f"{baseline}"
    )
    resolved_time = generated_at or current.created_at or "unrecorded"
    return MorningBrief(
        overall_status=status,
        generated_at=resolved_time,
        summary=summary,
        device_count=current.device_count,
        edge_count=current.edge_count,
        new_devices=new_devices,
        removed_devices=removed_devices,
        changed_devices=changed_devices,
        warnings=warnings,
        reconciliation_conflicts=conflicts,
        recommendations=recommendations,
        metadata={
            "current_snapshot_id": current.snapshot_id,
            "previous_snapshot_id": previous.snapshot_id if previous is not None else None,
            "deterministic": True,
            "in_memory_only": True,
            **(
                {"change_report": change_report.to_dict()}
                if change_report is not None
                else {}
            ),
            **(
                {"operational_report": state_report.to_dict()}
                if state_report is not None
                else {}
            ),
            **({"run": dict(run_context)} if run_context else {}),
        },
    )


def _devices_by_hostname(snapshot: TopologySnapshot | None) -> dict[str, dict[str, Any]]:
    if snapshot is None:
        return {}
    values = snapshot.to_dict()["devices"]
    return {str(device["hostname"]).casefold(): device for device in values}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _recommendations(
    removed: tuple[str, ...],
    changed: tuple[str, ...],
    warnings: tuple[dict[str, Any], ...],
    conflicts: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    recommendations: list[str] = []
    recommendations.extend(f"Verify reachability for removed device {name}." for name in removed)
    recommendations.extend(
        f"Review {name} configuration and topology changes." for name in changed
    )
    if conflicts:
        recommendations.append("Resolve topology reconciliation conflicts before operational decisions.")
    elif warnings:
        recommendations.append(f"Review {len(warnings)} topology warning(s).")
    if not recommendations:
        recommendations.append("No immediate topology action is required.")
    return tuple(recommendations)
