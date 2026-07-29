"""The ORACLE service: Atlas's stable AI interface (Parts 13-15).

Consumers — Advisor today; REST, CLI, automation, mobile, future
agents — depend on :class:`OracleService` and nothing else. They never
see a provider, a prompt, or an API key, and they never need to know
whether AI is configured: they ask for an enhancement and get either
the enhanced text or an honest refusal they can fall back from.

Every call passes the same gauntlet, in this order:

    feature flag -> governance policy -> capability availability
    -> configuration validity -> REDACTION -> provider -> audit

Redaction happens inside this service, not in the caller, because a
privacy guarantee that depends on every consumer remembering to call
it is not a guarantee. A provider is only ever handed text that has
already been through :mod:`.redaction`.

The contract that matters most is the failure contract: ``enhance()``
NEVER raises for an operational problem and never returns invented
content. It returns an :class:`Enhancement` whose ``ok`` is False and
whose ``fallback`` names the deterministic Atlas behaviour that
remains. AI being down is not an Atlas outage.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .capabilities import (
    DEFAULT_CAPABILITY_REGISTRY,
    AICapability,
    CapabilityRegistry,
)
from .config import (
    DISABLED_CONFIG,
    MODE_DISABLED,
    OracleConfig,
    OracleConfigRepository,
    validate,
)
from .contract import (
    AIMessage,
    AIProviderError,
    AIRequest,
    ProviderHealth,
    ProviderSettings,
    ROLE_SYSTEM,
    ROLE_USER,
)
from .prompts import (
    DEFAULT_PROMPT_REGISTRY,
    PromptError,
    PromptRegistry,
)
from .providers import (
    DEFAULT_PROVIDER_REGISTRY,
    KIND_DISABLED,
    ProviderRegistry,
)
from .redaction import RedactionPolicy, RedactionReport, redact
from .usage import (
    OUTCOME_BLOCKED,
    OUTCOME_DISABLED,
    OUTCOME_FAILED,
    OUTCOME_SUCCESS,
    UsageLedger,
    UsageRecord,
    estimate_cost,
)


@dataclass(frozen=True)
class Enhancement:
    """The result of an optional AI enhancement.

    ``ok`` False is a NORMAL outcome, not an error: it means Atlas
    shows its own deterministic output, which is always available.
    ``reason`` explains why to an operator; ``fallback`` states what
    Atlas does instead.
    """

    ok: bool
    text: str = ""
    reason: str = ""
    fallback: str = ""
    capability: str = ""
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    redactions: int = 0
    redaction_summary: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    latency_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "reason": self.reason,
            "fallback": self.fallback,
            "capability": self.capability,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "redactions": self.redactions,
            "redaction_summary": self.redaction_summary,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "latency_ms": self.latency_ms,
        }


class OracleService:
    """The one AI service. Constructing it reads configuration; it
    holds no provider until a call needs one."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        output_dir: str | Path | None = None,
        config: OracleConfig | None = None,
        repository: OracleConfigRepository | None = None,
        providers: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
        prompts: PromptRegistry = DEFAULT_PROMPT_REGISTRY,
        capabilities: CapabilityRegistry = DEFAULT_CAPABILITY_REGISTRY,
        ledger: UsageLedger | None = None,
        clock=None,
    ) -> None:
        self._repository = repository or OracleConfigRepository(
            workspace_root, registry=providers
        )
        self._config = config
        self._providers = providers
        self._prompts = prompts
        self._capabilities = capabilities
        self._ledger = ledger or UsageLedger(
            output_dir or self._repository.root
        )
        self._clock = clock or _utc_now
        self._lock = threading.Lock()

    # -- configuration ----------------------------------------------

    @property
    def config(self) -> OracleConfig:
        if self._config is None:
            self._config = self._repository.load()
        return self._config

    def reload(self) -> OracleConfig:
        """Re-read configuration — how a model or provider change takes
        effect without restarting Atlas (Part 5)."""

        with self._lock:
            self._config = self._repository.load()
        return self._config

    @property
    def enabled(self) -> bool:
        return self.config.mode != MODE_DISABLED

    def capability_available(self, key: str) -> bool:
        """Whether one capability would actually run right now."""

        return self._gate(key)[0] is not None

    # -- the public call --------------------------------------------

    def enhance(
        self,
        capability_key: str,
        variables: Mapping[str, Any],
        *,
        known_names: Iterable[str] = (),
        evidence_version: str = "",
    ) -> Enhancement:
        """Run one optional AI enhancement, or explain why it did not.

        ``variables`` fill the capability's registered prompt. Every
        value is redacted before it can reach a provider.
        """

        capability, refusal = self._gate(capability_key)
        if capability is None:
            self._audit_simple(
                capability_key, refusal.reason,
                OUTCOME_DISABLED if not self.enabled else OUTCOME_BLOCKED,
            )
            return refusal

        config = self.config
        template = self._prompts.get(capability.prompt)
        if template is None:
            return self._refuse(
                capability, "The prompt for this capability is not "
                "registered.", OUTCOME_BLOCKED,
            )

        # -- PRIVACY: nothing reaches a provider unredacted ----------
        policy = config.redaction_policy()
        if known_names:
            policy = policy.with_known_names(known_names)
        safe_variables: dict[str, Any] = {}
        report = RedactionReport()
        for name, value in variables.items():
            safe, item_report = redact(str(value), policy)
            safe_variables[name] = safe
            for label, count in item_report.counts.items():
                report.add(label, count)

        try:
            system, user = template.render(safe_variables)
        except PromptError as error:
            return self._refuse(
                capability, str(error), OUTCOME_BLOCKED, report=report,
            )

        provider = self._build_provider(config)
        request = AIRequest(
            messages=(
                AIMessage(ROLE_SYSTEM, system),
                AIMessage(ROLE_USER, user),
            ),
            model=config.model,
            max_output_tokens=min(
                capability.max_output_tokens, config.max_output_tokens
            ),
            temperature=config.temperature,
        )

        attempts = max(1, config.retries + 1)
        last_error = ""
        for attempt in range(attempts):
            try:
                result = provider.complete(request)
            except AIProviderError as error:
                last_error = error.reason
                if not error.retryable or attempt == attempts - 1:
                    break
                continue
            except Exception as error:  # a provider must never crash Atlas
                last_error = f"provider raised an unexpected error: {error}"
                break
            cost = estimate_cost(
                result.input_tokens, result.output_tokens,
                input_per_million=config.input_cost_per_million,
                output_per_million=config.output_cost_per_million,
            )
            self._ledger.record(UsageRecord(
                at=self._clock(), capability=capability.key,
                provider=result.provider, model=result.model,
                prompt_version=template.identifier,
                outcome=OUTCOME_SUCCESS,
                redaction_rules=tuple(config.redaction_rules),
                redactions=report.total,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost=cost, currency=config.currency,
                latency_ms=result.latency_ms, retries=attempt,
                evidence_version=evidence_version,
            ))
            return Enhancement(
                ok=True, text=result.text, capability=capability.key,
                provider=result.provider, model=result.model,
                prompt_version=template.identifier,
                redactions=report.total,
                redaction_summary=report.describe(),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost=cost, latency_ms=result.latency_ms,
                fallback=capability.fallback,
            )

        self._ledger.record(UsageRecord(
            at=self._clock(), capability=capability.key,
            provider=config.provider_kind, model=config.model,
            prompt_version=template.identifier, outcome=OUTCOME_FAILED,
            redaction_rules=tuple(config.redaction_rules),
            redactions=report.total, retries=attempts - 1,
            evidence_version=evidence_version, detail=last_error,
        ))
        return Enhancement(
            ok=False,
            reason=f"The AI provider did not answer: {last_error}",
            fallback=capability.fallback, capability=capability.key,
            provider=config.provider_kind, model=config.model,
            prompt_version=template.identifier,
            redactions=report.total,
            redaction_summary=report.describe(),
        )

    # -- gates -------------------------------------------------------

    def _gate(
        self, capability_key: str
    ) -> tuple[AICapability | None, Enhancement]:
        """(capability, refusal). The capability is None when the call
        must not proceed; the refusal always names the fallback."""

        capability = self._capabilities.get(capability_key)
        if capability is None:
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason=f"Unknown AI capability {capability_key!r}.",
                fallback="Atlas continues with its deterministic output.",
            )
        fallback = capability.fallback
        config = self.config
        if config.mode == MODE_DISABLED:
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason="AI is disabled for this workspace.",
                fallback=fallback,
            )
        if not capability.available:
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason="This AI capability is registered but not yet "
                       "available in this release.",
                fallback=fallback,
            )
        if not config.capability_enabled(capability_key):
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason="This AI capability is switched off.",
                fallback=fallback,
            )
        if not config.provider_allowed(config.provider_kind):
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason="The configured AI provider is not permitted by "
                       "policy.",
                fallback=fallback,
            )
        problems = validate(
            config, registry=self._providers,
            has_api_key=self._repository.has_api_key(config.provider_kind),
        )
        blocking = [
            problem for problem in problems
            if not problem.startswith("Warning:")
        ]
        if blocking:
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason="AI is not configured correctly: " + blocking[0],
                fallback=fallback,
            )
        if config.max_context_tokens < capability.min_context_tokens:
            return None, Enhancement(
                ok=False, capability=capability_key,
                reason="The configured model's context window is too "
                       "small for this capability.",
                fallback=fallback,
            )
        return capability, Enhancement(ok=False)

    def _refuse(
        self, capability: AICapability, reason: str, outcome: str,
        *, report: RedactionReport | None = None,
    ) -> Enhancement:
        self._ledger.record(UsageRecord(
            at=self._clock(), capability=capability.key,
            provider=self.config.provider_kind, model=self.config.model,
            prompt_version="", outcome=outcome,
            redactions=report.total if report else 0, detail=reason,
        ))
        return Enhancement(
            ok=False, reason=reason, fallback=capability.fallback,
            capability=capability.key,
        )

    def _audit_simple(self, capability_key: str, reason: str,
                      outcome: str) -> None:
        self._ledger.record(UsageRecord(
            at=self._clock(), capability=capability_key,
            provider=self.config.provider_kind, model=self.config.model,
            prompt_version="", outcome=outcome, detail=reason,
        ))

    # -- providers ---------------------------------------------------

    def _provider_settings(self, config: OracleConfig) -> ProviderSettings:
        return ProviderSettings(
            kind=config.provider_kind,
            endpoint=config.endpoint,
            model=config.model,
            api_key=self._repository.api_key(config.provider_kind),
            organization=config.organization,
            region=config.region,
            api_version=config.api_version,
            timeout_seconds=config.timeout_seconds,
            verify_tls=config.verify_tls,
            retries=config.retries,
            max_context_tokens=config.max_context_tokens,
        )

    def _build_provider(self, config: OracleConfig):
        descriptor = self._providers.get(config.provider_kind)
        if descriptor is None:
            descriptor = self._providers.get(KIND_DISABLED)
        return descriptor.build(self._provider_settings(config))

    # -- diagnostics (Part 13) ---------------------------------------

    def test_connection(
        self, config: OracleConfig | None = None
    ) -> ProviderHealth:
        """Probe the configured provider. Used by the settings page's
        Test Connection button; never raises."""

        config = config or self.config
        if config.provider_kind == KIND_DISABLED:
            return ProviderHealth(
                ok=False, detail="AI is disabled — nothing to test."
            )
        try:
            return self._build_provider(config).health()
        except AIProviderError as error:
            return ProviderHealth(ok=False, detail=error.reason)
        except Exception as error:  # never let a probe break the page
            return ProviderHealth(
                ok=False, detail=f"connection test failed: {error}"
            )

    def diagnostics(self, *, probe: bool = False) -> dict[str, Any]:
        """The AI diagnostics report. ``probe`` performs a live health
        check; without it the report is instant and offline."""

        config = self.config
        descriptor = self._providers.get(config.provider_kind)
        has_key = self._repository.has_api_key(config.provider_kind)
        report: dict[str, Any] = {
            "mode": config.mode,
            "enabled": self.enabled,
            "provider": config.provider_kind,
            "provider_label": descriptor.label if descriptor else "unknown",
            "hosting": descriptor.hosting if descriptor else "unknown",
            "model": config.model,
            "endpoint": config.endpoint or (
                descriptor.default_endpoint if descriptor else ""
            ),
            "authentication": "api key stored" if has_key
            else ("api key required" if descriptor
                  and descriptor.needs_api_key else "not required"),
            "verify_tls": config.verify_tls,
            "timeout_seconds": config.timeout_seconds,
            "max_context_tokens": config.max_context_tokens,
            "redaction_rules": list(config.redaction_rules),
            "problems": validate(
                config, registry=self._providers, has_api_key=has_key
            ),
            "providers_registered": [
                item.to_dict() for item in self._providers.descriptors()
            ],
            "prompts": [item.to_dict() for item in self._prompts.all()],
            "capabilities": [
                {
                    **item.to_dict(),
                    "enabled": config.capability_enabled(item.key),
                    "usable": self.capability_available(item.key),
                }
                for item in self._capabilities.all()
            ],
            "usage": self._ledger.summary(),
        }
        if probe:
            health = self.test_connection(config)
            report["connection"] = {
                "ok": health.ok, "detail": health.detail,
                "latency_ms": health.latency_ms,
                "models": list(health.models),
            }
        return report

    # -- usage (Part 9) ----------------------------------------------

    def usage_summary(self) -> dict[str, Any]:
        return self._ledger.summary()


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
