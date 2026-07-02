"""Pure structural rules shared by PlanValidator."""

from __future__ import annotations

from collections.abc import Iterable

from founderos_runtime.planner.execution_plan import ExecutionPlan

from .report import FindingSeverity, ValidationFinding


def error(code: str, message: str, subject: str) -> ValidationFinding:
    return ValidationFinding(code, FindingSeverity.ERROR, message, subject)


def duplicate_values(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def artifact_graph(plan: ExecutionPlan) -> tuple[dict[str, str], dict[str, set[str]]]:
    producers: dict[str, str] = {}
    dependencies = {step.id: set() for step in plan.steps}
    for step in plan.steps:
        for artifact_id in step.produced_artifacts:
            producers.setdefault(artifact_id, step.id)
    for step in plan.steps:
        for artifact_id in step.required_artifacts:
            producer = producers.get(artifact_id)
            if producer is not None:
                dependencies[step.id].add(producer)
    return producers, dependencies


def cyclic_nodes(dependencies: dict[str, set[str]]) -> tuple[str, ...]:
    remaining = {node: set(edges) for node, edges in dependencies.items()}
    while remaining:
        ready = sorted(node for node, edges in remaining.items() if not (edges & remaining.keys()))
        if not ready:
            return tuple(sorted(remaining))
        for node in ready:
            remaining.pop(node)
    return ()

