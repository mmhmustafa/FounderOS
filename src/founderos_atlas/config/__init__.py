"""Read-only configuration collection for Atlas."""

from .collector import (
    OPTIONAL_COMMANDS,
    RUNNING_CONFIG_COMMAND,
    collect_configuration,
)
from .models import (
    AtlasConfigurationError,
    COLLECTION_COMPLETE,
    COLLECTION_PARTIAL,
    CommandOutcome,
    ConfigurationArtifact,
    ConfigurationCollectionError,
)
from .storage import (
    ConfigurationArtifactPaths,
    safe_artifact_name,
    write_configuration_artifacts,
)

__all__ = [
    "AtlasConfigurationError",
    "COLLECTION_COMPLETE",
    "COLLECTION_PARTIAL",
    "CommandOutcome",
    "ConfigurationArtifact",
    "ConfigurationArtifactPaths",
    "ConfigurationCollectionError",
    "OPTIONAL_COMMANDS",
    "RUNNING_CONFIG_COMMAND",
    "collect_configuration",
    "safe_artifact_name",
    "write_configuration_artifacts",
]
