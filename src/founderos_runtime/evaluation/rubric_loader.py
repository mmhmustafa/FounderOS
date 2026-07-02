"""Load validated declarative Evaluation Rubrics without execution."""

from __future__ import annotations

from pathlib import Path

from founderos_runtime.manifest_loader import ManifestLoader

from .rubric import EvaluationRubric


class EvaluationRubricLoader:
    """Translate one validated rubric manifest into immutable Evaluation contracts."""

    def __init__(self, manifest_loader: ManifestLoader | None = None) -> None:
        self._manifest_loader = manifest_loader or ManifestLoader()

    def load(self, path: str | Path) -> EvaluationRubric:
        manifest = self._manifest_loader.load_evaluation_rubric_manifest(path)
        return EvaluationRubric.from_manifest(manifest)


def load_evaluation_rubric(path: str | Path) -> EvaluationRubric:
    return EvaluationRubricLoader().load(path)

