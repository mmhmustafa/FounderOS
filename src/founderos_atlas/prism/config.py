"""PRISM configuration and governance policy (PR-165, Parts 1, 11, 12).

Two stores, deliberately separated:

METADATA — ``prism.json`` in the workspace root: mode, provider kind,
endpoint, model, limits, redaction policy, governance restrictions and
per-capability feature flags. Plain JSON, atomically written, and
structurally incapable of holding a secret: :meth:`_reject_secrets`
refuses secret-named keys exactly as ``preferences.json`` does.

SECRET — the API key, held in Atlas's existing
:class:`CredentialProvider` (OS keyring, or AES-256-GCM encrypted file)
under the ref ``atlas-prism:<kind>``. Atlas has never had a plaintext
secret file and PRISM does not introduce one: if no secure store is
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
from . import semantic
from .redaction import OPTIONAL_RULES, RedactionPolicy, STRICT_POLICY


PRISM_FILENAME = "prism.json"
PRISM_SCHEMA_VERSION = "1.0.0"

CREDENTIAL_REF_PREFIX = "atlas-prism"

# This platform shipped under an earlier product name. The rename is
# complete in code, but a workspace configured under the old name still
# holds its settings and — in the secure store — its API key. These
# constants exist ONLY so the rename cannot silently discard an
# operator's configuration or orphan a credential they can no longer
# see to delete. Read-and-migrate: nothing is ever written under them,
# and a migrated key is removed from the old ref once the copy is
# verified. Delete this block once no deployment predates the rename.
LEGACY_FILENAME = "oracle.json"                    # RENAME-EXEMPT
LEGACY_DOCUMENT_KEY = "oracle"                     # RENAME-EXEMPT
LEGACY_CREDENTIAL_REF_PREFIX = "atlas-oracle"      # RENAME-EXEMPT

MODE_DISABLED = "disabled"
MODE_LOCAL = "local"
MODE_CLOUD = "cloud"

# Secret-named keys may never enter the metadata document. Same rule,
# same words, as workspace/administration.py — one convention.
FORBIDDEN_KEYS = frozenset(
    {"password", "secret", "token", "private_key", "passphrase", "api_key"}
)


def _privacy_profile(data: dict[str, Any]) -> str:
    """Which profile a stored document is running under.

    An explicit choice wins. Otherwise a document that already carries
    ``redaction_rules`` predates profiles and stays on those rules; a
    document without them is new and gets the Cloud profile — the
    stronger posture, never the weaker one.
    """

    explicit = str(data.get("privacy_profile") or "").strip()
    if explicit in semantic.PROFILE_BY_KEY or explicit == semantic.PROFILE_AUTO:
        return explicit
    return "" if "redaction_rules" in data else semantic.PROFILE_CLOUD


class PrismConfigError(ValueError):
    """An operator-readable configuration problem."""


def credential_ref_for(kind: str) -> str:
    """The credential ref holding one provider kind's API key."""

    return f"{CREDENTIAL_REF_PREFIX}:{kind}"


@dataclass(frozen=True)
class PrismConfig:
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
    # -- privacy (Part 8; profiles added in PR-166.2) ---------------
    redaction_rules: tuple[str, ...] = tuple(OPTIONAL_RULES)
    # Cloud by default — the stronger posture. Part 8 permits a local
    # model to preserve hostnames; it does not require Atlas to assume
    # it. A "local" endpoint may still be a proxy to a cloud model or a
    # service shared beyond this team, so preserving identifiers is an
    # administrator's explicit decision (the Internal profile, or the
    # "match the provider" choice), never an inference Atlas makes.
    # "" means this enterprise configured individual rules before
    # profiles existed; those rules stay in force until a profile is
    # chosen, so upgrading never silently changes a privacy posture.
    privacy_profile: str = semantic.PROFILE_CLOUD
    field_overrides: tuple[tuple[str, str], ...] = ()
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

    def active_profile(self) -> semantic.PrivacyProfile:
        """The privacy profile actually in force, overrides applied.

        ``auto`` resolves against how the provider is hosted: a model
        on your own network gets Internal, anything external gets
        Cloud (Parts 8 and 9).
        """

        key = str(self.privacy_profile or "")
        if key == semantic.PROFILE_AUTO:
            base = semantic.profile(semantic.profile_for_hosting(
                "local" if self.mode == MODE_LOCAL else "cloud"
            ))
        elif key in semantic.PROFILE_BY_KEY:
            base = semantic.profile(key)
        else:
            base = semantic.legacy_profile(self.redaction_rules)
        return base.with_overrides(dict(self.field_overrides))

    def redaction_policy(self) -> RedactionPolicy:
        return RedactionPolicy.from_names(
            self.active_profile().optional_rules()
        )

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
            "privacy_profile": self.privacy_profile,
            "field_overrides": {
                name: action for name, action in self.field_overrides
            },
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
    ) -> "PrismConfig":
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
            # A document written before profiles existed keeps its
            # explicit rules ("" = legacy) instead of being upgraded to
            # a posture nobody chose. A fresh document gets ``auto``.
            privacy_profile=_privacy_profile(data),
            field_overrides=tuple(
                (str(name), str(action))
                for name, action in sorted(
                    (data.get("field_overrides") or {}).items()
                )
                if name in semantic.FIELD_LABELS
                and action in semantic.ACTIONS
            ),
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


DISABLED_CONFIG = PrismConfig()


class PrismConfigRepository:
    """Reads and writes ``prism.json``; brokers the API key through
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
        self.path = self.root / PRISM_FILENAME
        self._registry = registry
        self._provider = credential_provider

    # -- metadata ----------------------------------------------------

    def load(self) -> PrismConfig:
        """The stored configuration, or the disabled default.

        A corrupt document reads as DISABLED rather than raising: a
        broken AI config must never take Atlas down, and silently
        enabling AI from garbage would be worse than either."""

        path = self.path
        if not path.is_file():
            legacy = self.root / LEGACY_FILENAME
            if not legacy.is_file():
                return DISABLED_CONFIG
            path = legacy
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DISABLED_CONFIG
        if not isinstance(payload, dict):
            return DISABLED_CONFIG
        # The document key was renamed with the product; read either.
        block = payload.get("prism")
        if block is None:
            block = payload.get(LEGACY_DOCUMENT_KEY) or {}
        return PrismConfig.from_dict(block, registry=self._registry)

    def save(self, config: PrismConfig, *, now: str) -> PrismConfig:
        """Persist metadata atomically. Refuses secrets structurally."""

        document = config.to_dict()
        _reject_secrets(document)
        stored = replace(config, updated_at=now)
        payload = {
            "schema_version": PRISM_SCHEMA_VERSION,
            "prism": stored.to_dict(),
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

    def _migrate_legacy_key(self, kind: str) -> str:
        """Carry a key stored under the pre-rename ref across to the
        PRISM ref, once. Returns the secret, or "".

        Without this, renaming the product would leave an operator's API
        key in the OS keyring under a name Atlas no longer reads and the
        settings page no longer shows — invisible, undeletable through
        the GUI, and still a live credential. The copy is verified
        before the old entry is removed."""

        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
            CredentialStoreUnavailableError,
        )

        legacy_ref = f"{LEGACY_CREDENTIAL_REF_PREFIX}:{kind}"
        try:
            provider = self._credentials()
            secret = provider.get(legacy_ref)
            if not secret:
                return ""
            provider.save(credential_ref_for(kind), secret)
            if provider.get(credential_ref_for(kind)) == secret:
                provider.delete(legacy_ref)  # only after a verified copy
            return secret
        except (CredentialNotFoundError, CredentialStoreUnavailableError):
            return ""

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
            if provider.get(credential_ref_for(kind)):
                return True
        except (CredentialNotFoundError, CredentialStoreUnavailableError):
            pass
        return bool(self._migrate_legacy_key(kind))

    def save_api_key(self, kind: str, api_key: str) -> None:
        """Store the key in the secure provider. Fails loudly when no
        secure store exists — Atlas never writes a secret in the clear."""

        from founderos_atlas.workspace.exceptions import (
            CredentialStoreUnavailableError,
        )

        provider = self._credentials()
        if not provider.available():
            raise PrismConfigError(
                "No secure credential store is available, so Atlas will "
                "not save an API key. Configure a keyring or the "
                "encrypted-file provider first — Atlas never writes "
                "secrets in the clear."
            )
        try:
            provider.save(credential_ref_for(kind), api_key)
        except CredentialStoreUnavailableError as error:
            raise PrismConfigError(str(error)) from error

    def delete_api_key(self, kind: str) -> None:
        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
            CredentialStoreUnavailableError,
        )

        for ref in (credential_ref_for(kind),
                    f"{LEGACY_CREDENTIAL_REF_PREFIX}:{kind}"):
            # Remove BOTH refs: "remove the stored key" must leave
            # nothing behind, including an un-migrated pre-rename entry.
            try:
                self._credentials().delete(ref)
            except (CredentialNotFoundError,
                    CredentialStoreUnavailableError):
                continue

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
            existing = provider.get(credential_ref_for(kind))
            if existing:
                return existing
        except (CredentialNotFoundError, CredentialStoreUnavailableError):
            # A missing key RAISES on the keyring provider, so the
            # legacy lookup has to sit outside this handler or the
            # migration would never run for the store that needs it.
            pass
        return self._migrate_legacy_key(kind)


def _reject_secrets(document: dict[str, Any]) -> None:
    for key in document:
        if key.casefold() in FORBIDDEN_KEYS:
            raise PrismConfigError(
                "Secret fields are not permitted in AI configuration "
                "metadata — API keys live in the credential store."
            )


def validate(
    config: PrismConfig,
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
    if config.is_cloud:
        active = config.active_profile()
        preserved = [
            semantic.FIELD_LABELS[name]
            for name in semantic.IDENTIFYING_FIELDS
            if active.preserves(name)
        ]
        if preserved:
            # Not an error: an informed choice. Stated plainly, and
            # naming the exact fields, so nobody sends identifying
            # detail to a third party by accident.
            problems.append(
                "Warning: identifying detail will be sent to a "
                "third-party provider — the “"
                f"{active.label}” profile preserves "
                f"{', '.join(preserved).lower()}."
            )
    return problems
