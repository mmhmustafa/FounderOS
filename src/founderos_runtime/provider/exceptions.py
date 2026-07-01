"""Typed Mock Provider boundary failures."""


class ProviderException(Exception):
    """Base exception for invalid local provider usage or configuration."""


class ProviderRequestError(ProviderException):
    """A ProviderRequest is structurally invalid."""


class ProviderFixtureError(ProviderException):
    """A fixture file or fixture entry is malformed or ambiguous."""


class ProviderFixtureNotFoundError(ProviderException):
    """Strict fixture mode has no response for the exact operation and input."""
