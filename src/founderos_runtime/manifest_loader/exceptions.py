"""Typed, contextual Manifest Loader failures."""

from __future__ import annotations

from pathlib import Path


class ManifestLoaderError(Exception):
    """Base error carrying stable file, field, and reason details."""

    def __init__(self, file: str | Path, field: str, reason: str) -> None:
        self.file = str(file)
        self.field = field
        self.reason = reason
        super().__init__(f"manifest error in {self.file} at {self.field}: {self.reason}")


class ManifestFileNotFoundError(ManifestLoaderError):
    """A requested manifest file does not exist."""


class ManifestReadError(ManifestLoaderError):
    """A manifest or schema file cannot be read."""


class ManifestYamlError(ManifestLoaderError):
    """A manifest is not well-formed YAML."""


class ManifestSchemaError(ManifestLoaderError):
    """A required manifest schema is missing, malformed, or invalid."""


class ManifestValidationError(ManifestLoaderError):
    """A parsed manifest violates its structural or semantic contract."""
