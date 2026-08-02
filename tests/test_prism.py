"""PR-165 (PRISM): Atlas's AI integration platform.

The contract these tests defend is the one the architecture rests on:
Atlas functions identically with AI disabled, no Atlas capability
depends on AI, providers are interchangeable, and nothing — secret,
hostname, or evidence — reaches a provider unredacted.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from founderos_atlas.prism import (
    CAPABILITY_EXECUTIVE_SUMMARY,
    CAPABILITY_PLAIN_ENGLISH,
    CLOUD_KINDS,
    DEFAULT_CAPABILITY_REGISTRY,
    DEFAULT_PROMPT_REGISTRY,
    DEFAULT_PROVIDER_REGISTRY,
    KIND_ANTHROPIC,
    KIND_DISABLED,
    KIND_OLLAMA,
    KIND_OPENAI,
    KIND_OPENROUTER,
    MODE_CLOUD,
    MODE_DISABLED,
    MODE_LOCAL,
    OPTIONAL_RULES,
    SAFETY_PREAMBLE,
    STRICT_POLICY,
    AIProviderError,
    AIResult,
    PrismConfig,
    PrismConfigError,
    PrismConfigRepository,
    PrismService,
    ProviderDescriptor,
    ProviderHealth,
    ProviderSettings,
    RedactionPolicy,
    UsageLedger,
    build_provider_registry,
    credential_ref_for,
    estimate_cost,
    redact,
    validate,
)
from founderos_atlas.prism.prompts import PromptError, PromptTemplate


# -- doubles ----------------------------------------------------------------

class RecordingProvider:
    """Captures what it was asked, so tests can prove what left Atlas."""

    kind = "recording"
    requests: list = []

    def __init__(self, settings) -> None:
        self.settings = settings

    def complete(self, request):
        RecordingProvider.requests.append(request)
        return AIResult(
            text="A plain-English restatement.", model=request.model,
            provider=self.kind, input_tokens=100, output_tokens=25,
            latency_ms=12,
        )

    def health(self):
        return ProviderHealth(ok=True, detail="ok", latency_ms=3,
                              models=("m1",))


class FlakyProvider(RecordingProvider):
    """Fails retryably a fixed number of times, then succeeds."""

    kind = "flaky"
    failures_remaining = 0

    def complete(self, request):
        if FlakyProvider.failures_remaining > 0:
            FlakyProvider.failures_remaining -= 1
            raise AIProviderError("temporary upstream failure",
                                  retryable=True)
        return super().complete(request)


class ExplodingProvider(RecordingProvider):
    """A misbehaving provider that raises something unexpected."""

    kind = "exploding"

    def complete(self, request):
        raise RuntimeError("provider library crashed")


class MemoryCredentials:
    def __init__(self, available: bool = True) -> None:
        self.store: dict[str, str] = {}
        self._available = available

    def available(self) -> bool:
        return self._available

    def save(self, ref: str, secret: str) -> None:
        self.store[ref] = secret

    def get(self, ref: str) -> str:
        return self.store.get(ref, "")

    def delete(self, ref: str) -> None:
        self.store.pop(ref, None)


def plain_vars(**overrides) -> dict:
    """The plain-english prompt's full variable set (v1.1.0 added the
    audience and the limitations, so both must always be supplied)."""

    base = {
        "finding": "All clear.", "confidence": "High",
        "limitations": "Atlas stated no limitations for this answer.",
        "audience": "a network engineer",
    }
    base.update(overrides)
    return base


def executive_vars(**overrides) -> dict:
    base = {
        "findings": "All clear.", "scope": "all", "confidence": "High",
        "limitations": "Atlas stated no limitations for this answer.",
        "audience": "a senior executive",
    }
    base.update(overrides)
    return base


def build_doubles_registry():
    registry = build_provider_registry()
    for double in (RecordingProvider, FlakyProvider, ExplodingProvider):
        registry.register(ProviderDescriptor(
            kind=double.kind, label=double.kind.title(), factory=double,
            hosting="local",
        ))
    return registry


class PrismHarness(unittest.TestCase):
    """Builds a service over a temporary workspace."""

    def setUp(self) -> None:
        RecordingProvider.requests = []
        FlakyProvider.failures_remaining = 0

    def service(self, tmp, config, *, credentials=None, providers=None):
        providers = providers or build_doubles_registry()
        repository = PrismConfigRepository(
            tmp, credential_provider=credentials or MemoryCredentials(),
            registry=providers,
        )
        repository.save(config, now="2026-07-27T00:00:00+00:00")
        service = PrismService(
            repository=repository, output_dir=tmp, providers=providers,
            clock=lambda: "2026-07-27T00:00:00+00:00",
        )
        return service, repository

    def working_config(self, **overrides) -> PrismConfig:
        base = PrismConfig(
            enabled=True, provider_kind="recording", model="local-1",
            enabled_capabilities=(CAPABILITY_PLAIN_ENGLISH,),
            redaction_rules=tuple(OPTIONAL_RULES),
        )
        return replace(base, **overrides) if overrides else base


# -- Part 1/2/5: modes, provider abstraction, model management --------------

class ProviderAbstractionTests(unittest.TestCase):
    def test_every_documented_provider_is_registered(self) -> None:
        kinds = set(DEFAULT_PROVIDER_REGISTRY.kinds())
        for expected in (
            KIND_DISABLED, KIND_OPENAI, "azure-openai", KIND_ANTHROPIC,
            "gemini", KIND_OPENROUTER, "openai-compatible", KIND_OLLAMA,
            "lm-studio", "vllm",
        ):
            self.assertIn(expected, kinds)

    def test_providers_declare_whether_data_leaves_the_network(self) -> None:
        by_kind = {
            item.kind: item for item in DEFAULT_PROVIDER_REGISTRY.descriptors()
        }
        self.assertEqual("cloud", by_kind[KIND_OPENAI].hosting)
        self.assertEqual("local", by_kind[KIND_OLLAMA].hosting)
        self.assertEqual("none", by_kind[KIND_DISABLED].hosting)
        # OpenRouter forwards to an upstream vendor, so it is cloud and
        # must be blocked by the same governance switch.
        self.assertEqual("cloud", by_kind[KIND_OPENROUTER].hosting)
        self.assertIn(KIND_OPENROUTER, CLOUD_KINDS)

    def test_openrouter_speaks_the_openai_wire_format(self) -> None:
        """It is an aggregator, so the only differences from OpenAI are
        the endpoint, the namespaced model id, and app attribution."""

        from founderos_atlas.prism.providers import OpenRouterProvider

        descriptor = DEFAULT_PROVIDER_REGISTRY.get(KIND_OPENROUTER)
        self.assertTrue(descriptor.needs_api_key)
        self.assertEqual(
            "https://openrouter.ai/api/v1", descriptor.default_endpoint
        )
        provider = OpenRouterProvider(ProviderSettings(
            kind=KIND_OPENROUTER, api_key="sk-or-test",
            model="anthropic/claude-sonnet-4",
        ))
        self.assertEqual(
            "https://openrouter.ai/api/v1/chat/completions",
            provider._completions_url(),
        )
        headers = provider._headers()
        self.assertEqual("Bearer sk-or-test", headers["Authorization"])
        self.assertEqual("FounderOS Atlas", headers["X-Title"])

    def test_a_future_provider_registers_without_touching_existing_code(
        self,
    ) -> None:
        registry = build_provider_registry()
        registry.register(ProviderDescriptor(
            kind="acme-llm", label="ACME", factory=RecordingProvider,
            hosting="local",
        ))
        self.assertIsNotNone(registry.get("acme-llm"))
        # And the built-in registry is untouched by that registration.
        self.assertIsNone(DEFAULT_PROVIDER_REGISTRY.get("acme-llm"))

    def test_duplicate_provider_kinds_are_refused(self) -> None:
        registry = build_provider_registry()
        with self.assertRaises(ValueError):
            registry.register(ProviderDescriptor(
                kind=KIND_OPENAI, label="dup", factory=RecordingProvider,
                hosting="cloud",
            ))

    def test_mode_is_derived_from_the_provider(self) -> None:
        self.assertEqual(MODE_DISABLED, PrismConfig().mode)
        self.assertEqual(
            MODE_DISABLED,
            PrismConfig(enabled=True, provider_kind=KIND_DISABLED).mode,
        )
        self.assertEqual(
            MODE_LOCAL,
            PrismConfig(enabled=True, provider_kind=KIND_OLLAMA).mode,
        )
        self.assertEqual(
            MODE_CLOUD,
            PrismConfig(enabled=True, provider_kind=KIND_OPENAI).mode,
        )


# -- Part 14 + success criteria: Atlas is identical with AI disabled --------

class DisabledModeTests(PrismHarness):
    def test_disabled_is_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = PrismService(workspace_root=tmp, output_dir=tmp)
            self.assertFalse(service.enabled)
            self.assertEqual(MODE_DISABLED, service.config.mode)

    def test_a_disabled_call_refuses_and_names_the_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(Path(tmp), PrismConfig())
            result = service.enhance(
                CAPABILITY_PLAIN_ENGLISH,
                {"finding": "All clear.", "confidence": "High"},
            )
            self.assertFalse(result.ok)
            self.assertEqual("", result.text)
            self.assertIn("disabled", result.reason)
            self.assertTrue(result.fallback)

    def test_every_capability_declares_a_deterministic_fallback(self) -> None:
        for capability in DEFAULT_CAPABILITY_REGISTRY.all():
            with self.subTest(capability=capability.key):
                self.assertTrue(capability.fallback.strip())

    def test_an_unknown_capability_refuses_rather_than_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(Path(tmp), self.working_config())
            result = service.enhance("not-a-capability", {})
            self.assertFalse(result.ok)
            self.assertIn("Unknown AI capability", result.reason)


# -- Part 8: privacy is enforced by the platform, not the caller -----------

class RedactionTests(unittest.TestCase):
    def test_mandatory_secrets_are_always_removed(self) -> None:
        text = (
            "snmp-server community S3cret RO\n"
            "username admin password Hunter2\n"
            "Authorization: Bearer eyJhbGciOi.payload.sig\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n"
            "-----END RSA PRIVATE KEY-----"
        )
        # Even with EVERY optional rule off, secrets go.
        safe, report = redact(text, RedactionPolicy())
        for secret in ("S3cret", "Hunter2", "eyJhbGciOi.payload.sig", "MIIE"):
            self.assertNotIn(secret, safe)
        self.assertGreaterEqual(report.total, 4)

    def test_optional_identity_rules_are_opt_in(self) -> None:
        text = "mumbai-core.example.net at 10.1.2.3 mac 00:1a:2b:3c:4d:5e"
        bare, _ = redact(text, RedactionPolicy())
        self.assertIn("10.1.2.3", bare)
        self.assertIn("mumbai-core.example.net", bare)
        strict, report = redact(text, STRICT_POLICY)
        self.assertNotIn("10.1.2.3", strict)
        self.assertNotIn("mumbai-core.example.net", strict)
        self.assertNotIn("00:1a:2b:3c:4d:5e", strict)
        self.assertIn("ip", report.counts)

    def test_known_names_redact_but_ordinary_words_survive(self) -> None:
        policy = STRICT_POLICY.with_known_names(["mumbai-core"])
        safe, _ = redact(
            "mumbai-core failed; snmp-server is read-only on this device.",
            policy,
        )
        self.assertNotIn("mumbai-core", safe)
        # Config keywords and prose are NOT hostnames — a guessing rule
        # would mangle the text it is meant to protect.
        self.assertIn("snmp-server", safe)
        self.assertIn("this device", safe)

    def test_placeholders_are_stable_within_one_pass(self) -> None:
        safe, _ = redact(
            "10.1.1.1 talks to 10.1.1.1 and to 10.2.2.2", STRICT_POLICY
        )
        tokens = [word for word in safe.split() if word.startswith("[redact")]
        self.assertEqual(3, len(tokens))
        self.assertEqual(2, len(set(tokens)))

    def test_redaction_never_nests_placeholders(self) -> None:
        safe, _ = redact(
            "password Hunter2 on host mumbai.example.net",
            STRICT_POLICY.with_known_names(["mumbai.example.net"]),
        )
        self.assertNotIn("[redacted:[redacted", safe)

    def test_the_report_states_what_was_removed(self) -> None:
        _, report = redact("snmp-server community S3cret", STRICT_POLICY)
        self.assertIn("snmp-community", report.describe())
        self.assertEqual(1, report.to_dict()["total"])


class RedactionIsEnforcedByTheServiceTests(PrismHarness):
    def test_nothing_reaches_a_provider_unredacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(Path(tmp), self.working_config())
            result = service.enhance(
                CAPABILITY_PLAIN_ENGLISH,
                plain_vars(
                    finding="mumbai-core (10.1.2.3) rejected "
                            "password Hunter2",
                ),
                known_names=["mumbai-core"],
            )
            self.assertTrue(result.ok, result.reason)
            sent = "\n".join(
                message.content
                for message in RecordingProvider.requests[-1].messages
            )
            for secret in ("Hunter2", "10.1.2.3", "mumbai-core"):
                self.assertNotIn(secret, sent)
            self.assertGreater(result.redactions, 0)
            self.assertTrue(result.redaction_summary)

    def test_every_prompt_carries_the_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(Path(tmp), self.working_config())
            service.enhance(CAPABILITY_PLAIN_ENGLISH, plain_vars())
            system = RecordingProvider.requests[-1].messages[0].content
            self.assertIn(SAFETY_PREAMBLE, system)
            # The clauses that matter, spelled out rather than implied.
            for clause in (
                "Never contradict",
                "Preserve uncertainty",
                "Never add devices",
                "Atlas — not you — determines every fact",
            ):
                self.assertIn(clause, system)


# -- Part 6/12: capability registry and feature flags ----------------------

class CapabilityGatingTests(PrismHarness):
    def test_capabilities_are_individually_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.working_config(
                enabled_capabilities=(CAPABILITY_PLAIN_ENGLISH,)
            )
            service, _ = self.service(Path(tmp), config)
            self.assertTrue(
                service.capability_available(CAPABILITY_PLAIN_ENGLISH)
            )
            self.assertFalse(
                service.capability_available(CAPABILITY_EXECUTIVE_SUMMARY)
            )
            blocked = service.enhance(
                CAPABILITY_EXECUTIVE_SUMMARY,
                {"findings": "x", "scope": "all"},
            )
            self.assertFalse(blocked.ok)
            self.assertIn("switched off", blocked.reason)

    def test_a_capability_marked_unavailable_never_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.working_config(
                enabled_capabilities=("conversation",)
            )
            service, _ = self.service(Path(tmp), config)
            result = service.enhance("conversation", {"finding": "x",
                                                      "confidence": "High"})
            self.assertFalse(result.ok)
            self.assertIn("not yet available", result.reason)


# -- Part 11: governance --------------------------------------------------

class GovernanceTests(PrismHarness):
    def test_cloud_providers_are_refused_unless_permitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            credentials = MemoryCredentials()
            config = self.working_config(
                provider_kind=KIND_OPENAI, model="gpt-x",
                allow_cloud_providers=False,
            )
            service, repository = self.service(
                Path(tmp), config, credentials=credentials,
            )
            repository.save_api_key(KIND_OPENAI, "sk-secret")
            result = service.enhance(
                CAPABILITY_PLAIN_ENGLISH,
                {"finding": "x", "confidence": "High"},
            )
            self.assertFalse(result.ok)
            self.assertEqual([], RecordingProvider.requests)

    def test_restricted_models_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.working_config(
                model="forbidden-1", allowed_models=("approved-1",),
            )
            service, _ = self.service(Path(tmp), config)
            result = service.enhance(
                CAPABILITY_PLAIN_ENGLISH,
                {"finding": "x", "confidence": "High"},
            )
            self.assertFalse(result.ok)
            self.assertIn("not configured correctly", result.reason)

    def test_restricted_providers_are_refused(self) -> None:
        config = self.working_config(
            provider_kind=KIND_OLLAMA, allowed_providers=(KIND_DISABLED,),
        )
        self.assertFalse(config.provider_allowed(KIND_OLLAMA))

    def test_validation_warns_before_identity_leaves_the_network(
        self,
    ) -> None:
        # PR-166.2: the privacy PROFILE now governs identity, so
        # "identity is unprotected" is expressed as a configuration
        # whose active profile preserves identifying fields. This is
        # the pre-profile shape — explicit rules, all of them off.
        config = PrismConfig(
            enabled=True, provider_kind=KIND_OPENAI, model="gpt-x",
            allow_cloud_providers=True, redaction_rules=(),
            privacy_profile="",
        )
        problems = validate(config, has_api_key=True)
        self.assertTrue(
            any(problem.startswith("Warning:") for problem in problems)
        )


# -- Part 1/4: configuration and secret handling ---------------------------

class ConfigurationTests(PrismHarness):
    def test_the_api_key_never_lands_in_the_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials = MemoryCredentials()
            _, repository = self.service(
                root, self.working_config(provider_kind=KIND_OPENAI),
                credentials=credentials,
            )
            repository.save_api_key(KIND_OPENAI, "sk-super-secret")
            document = (root / "prism.json").read_text(encoding="utf-8")
            self.assertNotIn("sk-super-secret", document)
            self.assertIn(
                "sk-super-secret",
                credentials.store[credential_ref_for(KIND_OPENAI)],
            )
            self.assertTrue(repository.has_api_key(KIND_OPENAI))

    def test_saving_a_key_without_a_secure_store_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = PrismConfigRepository(
                tmp, credential_provider=MemoryCredentials(available=False),
            )
            with self.assertRaises(PrismConfigError) as raised:
                repository.save_api_key(KIND_OPENAI, "sk-x")
            self.assertIn("never writes secrets in the clear",
                          str(raised.exception))

    def test_secret_named_fields_cannot_enter_the_metadata(self) -> None:
        from founderos_atlas.prism.config import _reject_secrets

        with self.assertRaises(PrismConfigError):
            _reject_secrets({"api_key": "sk-x"})

    def test_a_corrupt_config_reads_as_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prism.json").write_text("{not json", encoding="utf-8")
            repository = PrismConfigRepository(
                root, credential_provider=MemoryCredentials()
            )
            self.assertEqual(MODE_DISABLED, repository.load().mode)

    def test_values_are_clamped_to_sane_bounds(self) -> None:
        config = PrismConfig.from_dict({
            "timeout_seconds": 99999, "retries": 99, "temperature": 12.5,
            "max_output_tokens": -5,
        })
        self.assertEqual(600, config.timeout_seconds)
        self.assertEqual(5, config.retries)
        self.assertEqual(2.0, config.temperature)
        self.assertEqual(16, config.max_output_tokens)

    def test_an_unknown_provider_falls_back_to_disabled(self) -> None:
        config = PrismConfig.from_dict({"provider_kind": "not-real",
                                         "enabled": True})
        self.assertEqual(MODE_DISABLED, config.mode)

    def test_reload_picks_up_a_model_change_without_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, repository = self.service(root, self.working_config())
            self.assertEqual("local-1", service.config.model)
            repository.save(
                self.working_config(model="local-2"), now="2026-07-27T01:00:00+00:00"
            )
            self.assertEqual("local-2", service.reload().model)


# -- Part 7: prompt registry ----------------------------------------------

class PromptRegistryTests(unittest.TestCase):
    def test_every_prompt_is_versioned_and_purposeful(self) -> None:
        for prompt in DEFAULT_PROMPT_REGISTRY.all():
            with self.subTest(prompt=prompt.name):
                self.assertTrue(prompt.version)
                self.assertTrue(prompt.purpose)
                self.assertIn("@", prompt.identifier)

    def test_rendering_requires_every_declared_variable(self) -> None:
        prompt = DEFAULT_PROMPT_REGISTRY.get("plain-english")
        with self.assertRaises(PromptError):
            prompt.render({"finding": "only one"})

    def test_the_safety_preamble_cannot_be_skipped(self) -> None:
        prompt = DEFAULT_PROMPT_REGISTRY.get("plain-english")
        system, _ = prompt.render(plain_vars(finding="x"))
        self.assertTrue(system.startswith(SAFETY_PREAMBLE))

    def test_a_prompt_that_lies_about_its_variables_is_refused(self) -> None:
        from founderos_atlas.prism.prompts import PromptRegistry

        registry = PromptRegistry()
        with self.assertRaises(ValueError):
            registry.register(PromptTemplate(
                name="bad", version="1.0.0", purpose="x",
                system="", user="Hello {name}", variables=("other",),
            ))

    def test_re_registering_the_same_version_is_refused(self) -> None:
        from founderos_atlas.prism.prompts import PromptRegistry

        registry = PromptRegistry()
        template = PromptTemplate(
            name="p", version="1.0.0", purpose="x", system="", user="hi",
        )
        registry.register(template)
        with self.assertRaises(ValueError):
            registry.register(template)


# -- Parts 9/10: cost and audit -------------------------------------------

class UsageAndAuditTests(PrismHarness):
    def test_a_successful_call_is_audited_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, _ = self.service(root, self.working_config())
            service.enhance(
                CAPABILITY_PLAIN_ENGLISH,
                plain_vars(finding="secret-sauce phrase"),
            )
            records = UsageLedger(root).entries()
            self.assertEqual(1, len(records))
            record = records[0]
            self.assertEqual("success", record["outcome"])
            self.assertEqual(CAPABILITY_PLAIN_ENGLISH, record["capability"])
            self.assertTrue(record["prompt_version"])
            self.assertEqual(100, record["input_tokens"])
            raw = json.dumps(record)
            for banned in ("secret-sauce", "plain-English restatement"):
                self.assertNotIn(banned, raw)
            for field in ("prompt", "response", "messages", "api_key"):
                self.assertNotIn(field, record)

    def test_cost_is_estimated_only_when_it_can_be(self) -> None:
        self.assertIsNone(estimate_cost(
            100, 50, input_per_million=0.0, output_per_million=0.0
        ))
        self.assertIsNone(estimate_cost(
            None, None, input_per_million=1.0, output_per_million=2.0
        ))
        self.assertEqual(0.0002, estimate_cost(
            100, 50, input_per_million=1.0, output_per_million=2.0
        ))

    def test_the_dashboard_reports_how_much_it_could_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, _ = self.service(
                root, self.working_config(input_cost_per_million=1.0),
            )
            service.enhance(CAPABILITY_PLAIN_ENGLISH,
                            plain_vars(finding="a"))
            service.enhance(CAPABILITY_EXECUTIVE_SUMMARY,
                            executive_vars(findings="b"))
            summary = service.usage_summary()
            self.assertEqual(2, summary["requests"])
            self.assertEqual(1, summary["successes"])
            self.assertEqual(1, summary["cost_known_for"])
            self.assertIn(CAPABILITY_PLAIN_ENGLISH, summary["by_capability"])

    def test_a_refusal_is_audited_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, _ = self.service(root, PrismConfig())
            service.enhance(CAPABILITY_PLAIN_ENGLISH,
                            {"finding": "a", "confidence": "High"})
            records = UsageLedger(root).entries()
            self.assertEqual("disabled", records[0]["outcome"])


# -- Part 14: fallbacks ----------------------------------------------------

class FallbackTests(PrismHarness):
    def test_a_failing_provider_never_raises_into_atlas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.working_config(provider_kind="exploding",
                                         retries=0)
            service, _ = self.service(Path(tmp), config)
            result = service.enhance(
                CAPABILITY_PLAIN_ENGLISH,
                {"finding": "a", "confidence": "High"},
            )
            self.assertFalse(result.ok)
            self.assertEqual("", result.text)
            self.assertTrue(result.fallback)

    def test_retries_are_honoured_then_it_gives_up_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            FlakyProvider.failures_remaining = 1
            config = self.working_config(provider_kind="flaky", retries=1)
            service, _ = self.service(Path(tmp), config)
            recovered = service.enhance(
                CAPABILITY_PLAIN_ENGLISH, plain_vars(finding="a")
            )
            self.assertTrue(recovered.ok, recovered.reason)

            FlakyProvider.failures_remaining = 5
            gave_up = service.enhance(
                CAPABILITY_PLAIN_ENGLISH, plain_vars(finding="a")
            )
            self.assertFalse(gave_up.ok)
            self.assertIn("did not answer", gave_up.reason)


# -- Part 13: diagnostics --------------------------------------------------

class DiagnosticsTests(PrismHarness):
    def test_diagnostics_describe_the_platform_without_probing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(Path(tmp), self.working_config())
            report = service.diagnostics()
            self.assertEqual(MODE_LOCAL, report["mode"])
            self.assertTrue(report["providers_registered"])
            self.assertTrue(report["prompts"])
            self.assertTrue(report["capabilities"])
            self.assertIn("usage", report)
            self.assertNotIn("connection", report)
            json.dumps(report)  # JSON-safe by contract

    def test_a_probe_reports_provider_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(Path(tmp), self.working_config())
            report = service.diagnostics(probe=True)
            self.assertTrue(report["connection"]["ok"])
            self.assertEqual(["m1"], report["connection"]["models"])

    def test_diagnostics_never_expose_the_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            credentials = MemoryCredentials()
            service, repository = self.service(
                Path(tmp),
                self.working_config(provider_kind=KIND_OPENAI, model="gpt-x",
                                    allow_cloud_providers=True),
                credentials=credentials,
            )
            repository.save_api_key(KIND_OPENAI, "sk-do-not-leak")
            report = json.dumps(service.diagnostics())
            self.assertNotIn("sk-do-not-leak", report)
            self.assertIn("api key stored", report)


class AISettingsPageTests(unittest.TestCase):
    """The AI settings surface (Parts 1, 3, 4, 5, 9, 11, 12, 13)."""

    # The credential store is isolated for the whole session by
    # tests/__init__.py and tests/conftest.py, so saving an API key here
    # cannot reach the developer's real keyring.

    def build_client(self, workdir: Path):
        from tests.test_polish import build_world

        _, client = build_world(workdir)
        return client

    def test_the_page_leads_with_what_atlas_does_without_ai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/settings/ai").data
            self.assertIn(b"PRISM is optional", page)
            self.assertIn(b"What Atlas does when PRISM is off", page)
            self.assertIn(b"PRISM disabled", page)
            # Every capability's fallback is stated on the page.
            self.assertIn(b"deterministic answer with evidence", page)
            # And the privacy promise is visible, not buried.
            self.assertIn(b"always", page)

    def test_saving_settings_persists_and_audits_without_secrets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            response = client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": KIND_OLLAMA,
                "model": "llama-3", "endpoint": "http://localhost:11434/v1",
                "redaction_rules": list(OPTIONAL_RULES),
                "enabled_capabilities": [CAPABILITY_PLAIN_ENGLISH],
                "timeout_seconds": "20", "retries": "1",
                "max_context_tokens": "8192", "max_output_tokens": "500",
                "temperature": "0.2", "currency": "USD",
                "verify_tls": "1", "reason": "enable local AI",
            }, follow_redirects=True)
            self.assertEqual(200, response.status_code)
            config = PrismConfigRepository(workdir / "workspace").load()
            self.assertEqual(MODE_LOCAL, config.mode)
            self.assertEqual("llama-3", config.model)
            self.assertIn(CAPABILITY_PLAIN_ENGLISH,
                          config.enabled_capabilities)
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("ai-settings-update", audit)

    def test_a_stored_key_is_never_rendered_or_written_to_config(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": KIND_OPENAI,
                "model": "gpt-x", "allow_cloud_providers": "1",
                "currency": "USD",
            }, follow_redirects=True)
            saved = client.post("/settings/ai/key", data={
                "action": "save", "api_key": "sk-never-show-me",
                "reason": "configure cloud AI",
            }, follow_redirects=True)
            page = saved.data
            self.assertNotIn(b"sk-never-show-me", page)
            config_file = workdir / "workspace" / "prism.json"
            if config_file.is_file():
                self.assertNotIn(
                    "sk-never-show-me",
                    config_file.read_text(encoding="utf-8"),
                )
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("sk-never-show-me", audit)

    def test_the_diagnostics_endpoint_describes_the_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            report = client.get("/api/prism/diagnostics").get_json()
            self.assertEqual(MODE_DISABLED, report["mode"])
            self.assertFalse(report["enabled"])
            self.assertTrue(report["providers_registered"])
            self.assertTrue(report["capabilities"])
            self.assertIn("usage", report)

    def test_the_connection_test_reports_honestly_when_disabled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.post("/settings/ai/test", data={}).data
            self.assertIn(b"nothing to test", page)


if __name__ == "__main__":
    unittest.main()
