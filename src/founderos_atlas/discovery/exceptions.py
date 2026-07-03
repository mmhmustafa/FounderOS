"""Typed Atlas discovery failures."""


class AtlasDiscoveryError(Exception):
    """Base failure for deterministic Atlas discovery."""


class MissingCommandOutputError(AtlasDiscoveryError):
    """A required fixture command output was absent or empty."""


class UnsupportedAdapterError(AtlasDiscoveryError):
    """The supplied adapter does not implement the Atlas adapter contract."""


class DiscoveryParseError(AtlasDiscoveryError):
    """Fixture text could not be normalized into required facts."""
