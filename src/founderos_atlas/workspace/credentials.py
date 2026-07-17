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
from pathlib import Path

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


class EncryptedFileCredentialProvider(CredentialProvider):
    """AES-256-GCM encrypted secrets file for headless deployments.

    A server without an OS keyring (containers, service accounts) still
    must not write plaintext secrets. Secrets are sealed with a key the
    file NEVER contains: the operator supplies it as base64 in
    ``ATLAS_CREDENTIAL_KEY`` or, better, in a file named by
    ``ATLAS_CREDENTIAL_KEY_FILE`` (a mounted secret). Each value gets a
    fresh 96-bit nonce; the credential ref is bound as associated data,
    so a ciphertext moved to another ref refuses to decrypt.

    This is also the adapter seam for Vault/KMS: such a provider would
    subclass CredentialProvider the same way and replace this one via
    ``ATLAS_CREDENTIAL_PROVIDER``.
    """

    FILENAME = "credentials.enc.json"

    def __init__(self, root: str | Path | None = None, *, key: bytes | None = None) -> None:
        from .repository import default_workspace_root

        self._root = Path(root) if root is not None else default_workspace_root()
        self._key = key if key is not None else _load_credential_key()

    @property
    def path(self) -> Path:
        return self._root / self.FILENAME

    def available(self) -> bool:
        if self._key is None:
            return False
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            return False
        return True

    def _cipher(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if self._key is None:
            raise CredentialStoreUnavailableError(
                "The encrypted credential store needs a key: set "
                "ATLAS_CREDENTIAL_KEY (base64, 32 bytes) or "
                "ATLAS_CREDENTIAL_KEY_FILE."
            )
        return AESGCM(self._key)

    def _load(self) -> dict:
        import json

        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _store(self, entries: dict) -> None:
        import json
        from uuid import uuid4

        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                json.dumps(
                    {"schema_version": "1.0.0",
                     "secrets": entries.get("secrets", entries)},
                    indent=2, sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, credential_ref: str, password: str) -> None:
        import base64
        import os as _os

        self._require(credential_ref, password)
        cipher = self._cipher()
        nonce = _os.urandom(12)
        sealed = cipher.encrypt(
            nonce, password.encode("utf-8"), credential_ref.encode("utf-8")
        )
        data = self._load()
        secrets_map = data.get("secrets") if isinstance(data, dict) else None
        secrets_map = dict(secrets_map or {})
        secrets_map[credential_ref] = base64.b64encode(nonce + sealed).decode("ascii")
        self._store({"secrets": secrets_map})

    def get(self, credential_ref: str) -> str:
        import base64

        self._require(credential_ref)
        data = self._load()
        secrets_map = (data.get("secrets") if isinstance(data, dict) else {}) or {}
        blob = secrets_map.get(credential_ref)
        if blob is None:
            raise CredentialNotFoundError(
                "No stored credential was found for this profile."
            )
        raw = base64.b64decode(blob)
        try:
            return self._cipher().decrypt(
                raw[:12], raw[12:], credential_ref.encode("utf-8")
            ).decode("utf-8")
        except Exception as error:
            raise CredentialStoreUnavailableError(
                "The stored credential could not be decrypted — the key is "
                "wrong or the record is damaged."
            ) from error

    def delete(self, credential_ref: str) -> None:
        self._require(credential_ref)
        data = self._load()
        secrets_map = (data.get("secrets") if isinstance(data, dict) else {}) or {}
        if credential_ref in secrets_map:
            secrets_map = dict(secrets_map)
            del secrets_map[credential_ref]
            self._store({"secrets": secrets_map})


def _load_credential_key() -> bytes | None:
    import base64
    import os as _os

    key_file = _os.environ.get("ATLAS_CREDENTIAL_KEY_FILE", "").strip()
    encoded = _os.environ.get("ATLAS_CREDENTIAL_KEY", "").strip()
    if key_file:
        try:
            encoded = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None
    if not encoded:
        return None
    try:
        key = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None
    return key if len(key) == 32 else None


def resolve_credential_provider() -> CredentialProvider:
    """The configured secure provider (OS keyring by default).

    ``ATLAS_CREDENTIAL_PROVIDER``: ``keyring`` (default), ``encrypted-file``
    (headless servers; see EncryptedFileCredentialProvider), or ``memory``
    (tests only — never persists). There is deliberately no plaintext file
    option.
    """

    import os as _os

    choice = _os.environ.get("ATLAS_CREDENTIAL_PROVIDER", "keyring").strip()
    if choice == "encrypted-file":
        return EncryptedFileCredentialProvider()
    if choice == "memory":
        return InMemoryCredentialProvider()
    return KeyringCredentialProvider()
