"""Credential provider abstraction and secure local implementations.

Profiles store only a ``credential_ref``; the actual password lives here,
in a secure store. The abstraction keeps Atlas extensible for future
enterprise backends (HashiCorp Vault, AWS Secrets Manager, Azure Key
Vault) without changing the profile model or service.

There is deliberately **no plaintext file provider**: if no secure store is
available, credential operations fail loudly rather than writing a secret to
disk in the clear.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .exceptions import (
    CredentialNotFoundError,
    CredentialStoreUnavailableError,
)


KEYRING_SERVICE = "founderos-atlas"


class CredentialProvider(ABC):
    """Secure store for profile passwords, keyed by an opaque credential ref."""

    @abstractmethod
    def available(self) -> bool:
        """Whether this provider can actually store and retrieve secrets."""

    @abstractmethod
    def save(self, credential_ref: str, password: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, credential_ref: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def delete(self, credential_ref: str) -> None:
        raise NotImplementedError

    def _require(self, credential_ref: str, password: str | None = None) -> None:
        if not isinstance(credential_ref, str) or not credential_ref.strip():
            raise ValueError("credential_ref must be a non-empty string")
        if password is not None and not password:
            raise ValueError("password must be non-empty")


class KeyringCredentialProvider(CredentialProvider):
    """OS-native secure storage via the ``keyring`` library (optional dep)."""

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self._service = service

    def _keyring(self):
        try:
            import keyring
        except ImportError as error:  # pragma: no cover - exercised via factory
            raise CredentialStoreUnavailableError(
                "Secure credential storage requires the 'keyring' package. "
                "Install it with: pip install founderos-runtime[credentials]"
            ) from error
        return keyring

    def available(self) -> bool:
        try:
            keyring = self._keyring()
        except CredentialStoreUnavailableError:
            return False
        try:
            from keyring.backends.fail import Keyring as FailKeyring

            return not isinstance(keyring.get_keyring(), FailKeyring)
        except Exception:  # pragma: no cover - defensive
            return True

    def save(self, credential_ref: str, password: str) -> None:
        self._require(credential_ref, password)
        keyring = self._keyring()
        try:
            keyring.set_password(self._service, credential_ref, password)
        except Exception as error:  # pragma: no cover - backend specific
            raise CredentialStoreUnavailableError(
                f"Could not store the credential securely: {error}"
            ) from error

    def get(self, credential_ref: str) -> str:
        self._require(credential_ref)
        keyring = self._keyring()
        try:
            password = keyring.get_password(self._service, credential_ref)
        except Exception as error:  # pragma: no cover - backend specific
            raise CredentialStoreUnavailableError(
                f"Could not read the credential securely: {error}"
            ) from error
        if password is None:
            raise CredentialNotFoundError(
                "No stored credential was found for this profile. "
                "Update the profile to set the password again."
            )
        return password

    def delete(self, credential_ref: str) -> None:
        self._require(credential_ref)
        keyring = self._keyring()
        try:
            keyring.delete_password(self._service, credential_ref)
        except Exception:
            # Deleting a non-existent credential is not an error.
            pass


class InMemoryCredentialProvider(CredentialProvider):
    """Process-local store. For tests and single-process sessions only.

    It never touches disk, so secrets do not persist across CLI invocations;
    it exists so the profile/service layer can be exercised without an OS
    keyring backend.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def save(self, credential_ref: str, password: str) -> None:
        self._require(credential_ref, password)
        self._store[credential_ref] = password

    def get(self, credential_ref: str) -> str:
        self._require(credential_ref)
        try:
            return self._store[credential_ref]
        except KeyError as error:
            raise CredentialNotFoundError(
                "No stored credential was found for this profile."
            ) from error

    def delete(self, credential_ref: str) -> None:
        self._require(credential_ref)
        self._store.pop(credential_ref, None)


def resolve_credential_provider() -> CredentialProvider:
    """Return the best available secure provider (OS keyring by default)."""

    return KeyringCredentialProvider()
