"""ORACLE configuration and governance policy (PR-165, Parts 1, 11, 12).

Two stores, deliberately separated:

METADATA — ``oracle.json`` in the workspace root: mode, provider kind,
endpoint, model, limits, redaction policy, governance restrictions and
per-capability feature flags. Plain JSON, atomically written, and
structurally incapable of holding a secret: :meth:`_reject_secrets`
refuses secret-named keys exactly as ``preferences.json`` does.

SECRET — the API key, held in Atlas's existing
:class:`CredentialProvider` (OS keyring, or AES-256-GCM encrypted file)
under the ref ``atlas-oracle:<kind>``. Atlas has never had a plaintext
secret file and ORACLE does not introduce one: if no secure store is
available, saving a key fails loudly rather than writing it in the
clear.

Governance (Part 11) lives here too, because a policy that is not part
of the configuration is a policy nobody can audit: administrators may
forbid cloud providers outright, restrict which providers and models
may be selected, and enable capabilities one at a time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .providers import (
    CLOUD_KINDS,
    DEFAULT_PROVIDER_REGISTRY,
    KIND_DISABLED,
    ProviderRegistry,
)
from .redaction import OPTIONAL_RULES, RedactionPolicy, STRICT_POLICY


ORACLE_FILENAME = "oracle.json"
ORACLE_SCHEMA_VERSION = "1.0.0"

CREDENTIAL_REF_PREFIX = "atlas-oracle"

MODE_DISABLED = "disabled"
MODE_LOCAL = "local"
MODE_CLOUD = "cloud"

# Secret-named keys may never enter the metadata document. Same rule,
# same words, as workspace/administration.py — one convention.
FORBIDDEN_KEYS = frozenset(
    {"password", "secret", "token", "private_key", "passphrase", "api_key"}
)


class OracleConfigError(ValueError):
    """An operator-readable configuration problem."""


def credential_ref_for(kind: str) -> str:
    """The credential ref holding one provider kind's API key."""

    return f"{CREDENTIAL_REF_PREFIX}:{kind}"


@dataclass(frozen=True)
class OracleConfig:
    """The whole AI configuration except the API key itself."""

    enabled: bool = False
    provider_kind: str = KIND_DISABLED
    endpoint: str = ""
    model: str = ""
    organization: str = ""
    region: str = ""
    api_version: str = ""
    timeout_seconds: int = 30
    verify_tls: bool = True
    retries: int = 1
    max_context_tokens: int = 8192
    max_output_tokens: int = 800
    temperature: float = 0.2
    # -- privacy (Part 8) -------------------------------------------
    redaction_rules: tuple[str, ...] = tuple(OPTIONAL_RULES)
    # -- governance (Part 11) ---------------------------------------
    allow_cloud_providers: bool = False
    allowed_providers: tuple[str, ...] = ()   # () = every registered kind
    allowed_models: tuple[str, ...] = ()      # () = any model
    # -- feature flags (Part 12) ------------------------------------
    enabled_capabilities: tuple[str, ...] = ()
    # -- cost (Part 9) ----------------------------------------------
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    currency: str = "USD"
    updated_at: str | None = None

    # -- derived ----------------------------------------------------

    @property
    def mode(self) -> str:
        """Disabled / Local AI / Cloud AI — the three modes of Part 1."""

        if not self.enabled or self.provider_kind == KIND_DISABLED:
            return MODE_DISABLED
        return MODE_CLOUD if self.provider_kind in CLOUD_KINDS else MODE_LOCAL

    @property
    def is_cloud(self) -> bool:
        return self.mode == MODE_CLOUD

    def redaction_policy(self) -> RedactionPolicy:
        return RedactionPolicy.from_names(self.redaction_rules)

    def capability_enabled(self, name: str) -> bool:
        return name in self.enabled_capabilities

    def provider_allowed(self, kind: str) -> bool:
        if self.allowed_providers and kind not in self.allowed_providers:
            return False
        if kind in CLOUD_KINDS and not self.allow_cloud_providers:
            return False
        return True

    def model_allowed(self, model: str) -> bool:
        return not self.allowed_models or model in self.allowed_models

    # -- serialization ----------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider_kind": self.provider_kind,
            "endpoint": self.endpoint,
            "model": self.model,
            "organization": self.organization,
            "region": self.region,
            "api_version": self.api_version,
            "timeout_seconds": self.timeout_seconds,
            "verify_tls": self.verify_tls,
            "retries": self.retries,
            "max_context_tokens": self.max_context_tokens,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "redaction_rules": list(self.redaction_rules),
            "allow_cloud_providers": self.allow_cloud_providers,
            "allowed_providers": list(self.allowed_providers),
            "allowed_models": list(self.allowed_models),
            "enabled_capabilities": list(self.enabled_capabilities),
            "input_cost_per_million": self.input_cost_per_million,
            "output_cost_per_million": self.output_cost_per_million,
            "currency": self.currency,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any] | None,
        *, registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> "OracleConfig":
        """Tolerant of older/partial documents; validates what matters.

        A configuration that cannot be understood must not silently
        enable AI — every failure path here lands on 'disabled'."""

        data = dict(payload or {})
        kind = str(data.get("provider_kind") or KIND_DISABLED)
        if registry.get(kind) is None:
            kind = KIND_DISABLED
        rules = tuple(
            rule for rule in (data.get("redaction_rules") or [])
            if rule in OPTIONAL_RULES
        )
        return cls(
            enabled=bool(data.get("enabled", False)),
            provider_kind=kind,
            endpoint=str(data.get("endpoint") or ""),
            model=str(data.get("model") or ""),
            organization=str(data.get("organization") or ""),
            region=str(data.get("region") or ""),
            api_version=str(data.get("api_version") or ""),
            timeout_seconds=_bounded_int(
                data.get("timeout_seconds"), 30, 1, 600
            ),
            verify_tls=bool(data.get("verify_tls", True)),
            retries=_bounded_int(data.get("retries"), 1, 0, 5),
            max_context_tokens=_bounded_int(
                data.get("max_context_tokens"), 8192, 256, 2_000_000
            ),
            max_output_tokens=_bounded_int(
                data.get("max_output_tokens"), 800, 16, 32_000
            ),
            temperature=_bounded_float(data.get("temperature"), 0.2, 0.0, 2.0),
            redaction_rules=rules if rules else (),
            allow_cloud_providers=bool(
                data.get("allow_cloud_providers", False)
            ),
            allowed_providers=tuple(
                str(item) for item in (data.get("allowed_providers") or [])
            ),
            allowed_models=tuple(
                str(item) for item in (data.get("allowed_models") or [])
            ),
            enabled_capabilities=tuple(
                str(item) for item in (data.get("enabled_capabilities") or [])
            ),
            input_cost_per_million=_bounded_float(
                data.get("input_cost_per_million"), 0.0, 0.0, 10_000.0
            ),
            output_cost_per_million=_bounded_float(
                data.get("output_cost_per_million"), 0.0, 0.0, 10_000.0
            ),
            currency=str(data.get("currency") or "USD")[:8],
            updated_at=data.get("updated_at") or None,
        )


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _bounded_float(value: Any, default: float, low: float, high: float
                   ) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


DISABLED_CONFIG = OracleConfig()


class OracleConfigRepository:
    """Reads and writes ``oracle.json``; brokers the API key through
    the workspace credential provider."""

    def __init__(
        self, workspace_root: str | Path | None = None,
        *, credential_provider: Any | None = None,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        from founderos_atlas.workspace.repository import (
            default_workspace_root,
        )

        self.root = Path(workspace_root or default_workspace_root())
        self.path = self.root / ORACLE_FILENAME
        self._registry = registry
        self._provider = credential_provider

    # -- metadata ----------------------------------------------------

    def load(self) -> OracleConfig:
        """The stored configuration, or the disabled default.

        A corrupt document reads as DISABLED rather than raising: a
        broken AI config must never take Atlas down, and silently
        enabling AI from garbage would be worse than either."""

        if not self.path.is_file():
            return DISABLED_CONFIG
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DISABLED_CONFIG
        if not isinstance(payload, dict):
            return DISABLED_CONFIG
        return OracleConfig.from_dict(
            payload.get("oracle") or {}, registry=self._registry
        )

    def save(self, config: OracleConfig, *, now: str) -> OracleConfig:
        """Persist metadata atomically. Refuses secrets structurally."""

        document = config.to_dict()
        _reject_secrets(document)
        stored = replace(config, updated_at=now)
        payload = {
            "schema_version": ORACLE_SCHEMA_VERSION,
            "oracle": stored.to_dict(),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True,
                           ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return stored

    # -- the secret --------------------------------------------------

    def _credentials(self):
        if self._provider is None:
            from founderos_atlas.workspace.credentials import (
                resolve_credential_provider,
            )

            self._provider = resolve_credential_provider()
        return self._provider

    def has_api_key(self, kind: str) -> bool:
        """Whether a key is stored — never the key itself."""

        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
            CredentialStoreUnavailableError,
        )

        try:
            provider = self._credentials()
            if not provider.available():
                return False
            return bool(provider.get(credential_ref_for(kind)))
        except (CredentialNotFoundError, CredentialStoreUnavailableError):
            return False

    def save_api_key(self, kind: str, api_key: str) -> None:
        """Store the key in the secure provider. Fails loudly when no
        secure store exists — Atlas never writes a secret in the clear."""

        from founderos_atlas.workspace.exceptions import (
            CredentialStoreUnavailableError,
        )

        provider = self._credentials()
        if not provider.available():
            raise OracleConfigError(
                "No secure credential store is available, so Atlas will "
                "not save an API key. Configure a keyring or the "
                "encrypted-file provider first — Atlas never writes "
                "secrets in the clear."
            )
        try:
            provider.save(credential_ref_for(kind), api_key)
        except CredentialStoreUnavailableError as error:
            raise OracleConfigError(str(error)) from error

    def delete_api_key(self, kind: str) -> None:
        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
            CredentialStoreUnavailableError,
        )

        try:
            self._credentials().delete(credential_ref_for(kind))
        except (CredentialNotFoundError, CredentialStoreUnavailableError):
            pass

    def api_key(self, kind: str) -> str:
        """The plaintext key, for one call, held only in memory."""

        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
            CredentialStoreUnavailableError,
        )

        try:
            provider = self._credentials()
            if not provider.available():
                return ""
            return provider.get(credential_ref_for(kind)) or ""
        except (CredentialNotFoundError, CredentialStoreUnavailableError):
            return ""


def _reject_secrets(document: dict[str, Any]) -> None:
    for key in document:
        if key.casefold() in FORBIDDEN_KEYS:
            raise OracleConfigError(
                "Secret fields are not permitted in AI configuration "
                "metadata — API keys live in the credential store."
            )


def validate(
    config: OracleConfig,
    *,
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    has_api_key: bool = False,
) -> list[str]:
    """Operator-readable problems with a configuration, or []. Checked
    before AI can be enabled — a misconfiguration must be visible in
    the settings page, not discovered by a failing answer."""

    problems: list[str] = []
    descriptor = registry.get(config.provider_kind)
    if descriptor is None:
        return [f"Unknown provider {config.provider_kind!r}."]
    if not config.enabled or config.provider_kind == KIND_DISABLED:
        return problems
    if not config.provider_allowed(config.provider_kind):
        problems.append(
            f"{descriptor.label} is not permitted by the current AI "
            "governance policy."
        )
    if descriptor.needs_endpoint and not config.endpoint.strip():
        problems.append(f"{descriptor.label} requires an endpoint URL.")
    if config.endpoint and not config.endpoint.startswith(
        ("http://", "https://")
    ):
        problems.append("The endpoint must start with http:// or https://.")
    if descriptor.needs_api_key and not has_api_key:
        problems.append(f"{descriptor.label} requires an API key.")
    if not config.model.strip():
        problems.append("Choose a model.")
    elif not config.model_allowed(config.model):
        problems.append(
            f"Model {config.model!r} is not in the permitted model list."
        )
    if config.is_cloud and not config.allow_cloud_providers:
        problems.append(
            "Cloud AI is disabled by policy. Enable cloud providers "
            "first, or choose a customer-hosted provider."
        )
    if (config.is_cloud
            and not set(config.redaction_rules) >= set(OPTIONAL_RULES)):
        # Not an error: an informed choice. Stated plainly so nobody
        # sends identifying detail to a third party by accident.
        problems.append(
            "Warning: identifying detail (see the redaction options) "
            "will be sent to a third-party provider."
        )
    return problems
