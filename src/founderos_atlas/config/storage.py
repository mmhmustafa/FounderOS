"""Local artifact file delivery for collected configurations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .models import ConfigurationArtifact


_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class ConfigurationArtifactPaths:
    directory: Path
    running_config: Path
    metadata: Path
    additional: tuple[Path, ...] = ()


def safe_artifact_name(value: str) -> str:
    """Filesystem-safe name derived from a hostname or command."""

    cleaned = _UNSAFE_CHARACTERS.sub("_", value.strip())
    return cleaned or "device"


def write_configuration_artifacts(
    artifact: ConfigurationArtifact, directory: str | Path
) -> ConfigurationArtifactPaths:
    """Write running_config.txt, configuration_metadata.json, and extras.

    The directory should be treated as sensitive: it contains device
    configuration material.
    """

    if not isinstance(artifact, ConfigurationArtifact):
        raise TypeError("artifact must be a ConfigurationArtifact")
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)

    running_config_path = target / "running_config.txt"
    running_config_path.write_text(artifact.running_config, encoding="utf-8")

    metadata_path = target / "configuration_metadata.json"
    metadata_path.write_text(
        json.dumps(
            artifact.to_metadata_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    additional_paths: list[Path] = []
    for command in sorted(artifact.additional_outputs):
        path = target / f"{safe_artifact_name(command.replace(' ', '_'))}.txt"
        path.write_text(artifact.additional_outputs[command], encoding="utf-8")
        additional_paths.append(path)

    return ConfigurationArtifactPaths(
        directory=target,
        running_config=running_config_path,
        metadata=metadata_path,
        additional=tuple(additional_paths),
    )
