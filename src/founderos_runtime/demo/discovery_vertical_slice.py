"""Run the first-party Discovery example entirely in memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from founderos_runtime.evaluation import load_evaluation_rubric
from founderos_runtime.journey import JourneyResult, JourneyRunner
from founderos_runtime.provider import MockProvider
from founderos_runtime.workspace import Workspace


DISCOVERY_WORKFLOW_ID = "wfl_01ARZ3NDEKTSV4RRFFQ69G5FAW"


def discovery_example_root() -> Path:
    return Path(__file__).resolve().parents[3] / "examples" / "discovery_vertical_slice"


def load_discovery_workspace(root: str | Path | None = None) -> Workspace:
    return Workspace.load(Path(root) if root is not None else discovery_example_root())


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _rubric_resolver(root: Path):
    resolved_root = root.resolve()

    def resolve(declaration):
        rubric_path = (resolved_root / declaration["rubric_ref"]).resolve()
        try:
            rubric_path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError("rubric reference escapes the Discovery example root") from error
        return load_evaluation_rubric(rubric_path)

    return resolve


def run_discovery_vertical_slice(
    root: str | Path | None = None,
) -> JourneyResult:
    """Load, plan, validate, authorize, generate, evaluate, and return one Journey."""

    example_root = Path(root) if root is not None else discovery_example_root()
    workspace = load_discovery_workspace(example_root)
    provider = MockProvider.from_fixtures(
        example_root / "fixtures" / "mock-provider-responses.json"
    )
    founder_brief = _read_json(example_root / "fixtures" / "founder-brief.json")
    runner = JourneyRunner(
        workspace,
        provider=provider,
        rubric_resolver=_rubric_resolver(example_root),
    )
    return runner.run(
        DISCOVERY_WORKFLOW_ID,
        input_artifacts={"founder_brief": founder_brief},
    )

