"""PR-166 (INSIGHT): Advisor's optional AI explanation.

The contract under test is a negative one: Atlas answers exactly as it
did before, AI only restates them, and every AI failure is invisible to
the operator beyond a calm note that the enhancement is unavailable.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from founderos_atlas.advisor.explanation import (
    AUDIENCES,
    DEFAULT_AUDIENCE,
    LANGUAGES,
    Explanation,
    explain,
    finding_text,
    limitations_text,
    panel_context,
)
from founderos_atlas.prism import (
    CAPABILITY_EXECUTIVE_SUMMARY,
    CAPABILITY_PLAIN_ENGLISH,
    CAPABILITY_TRANSLATION,
    AIProviderError,
    AIResult,
    PrismConfig,
    PrismConfigRepository,
    PrismService,
    ProviderDescriptor,
    ProviderHealth,
    build_provider_registry,
)

STORED_ANSWER = {
    "question": "Is Mumbai healthy?",
    "intent": "health",
    "summary": "mumbai-core is degraded: 1 active issue. BGP session to "
               "chennai-edge flapped. Discovery is 92% complete.",
    "evidence": [
        {"label": "Enterprise Graph", "detail": "snapshot 8f2a",
         "href": "/topology"},
        {"label": "Change Report", "detail": "2 changes in 24h",
         "href": "/changes"},
    ],
    "confidence": "Medium",
    "confidence_basis": "discovery is complete but evidence is 30 hours old",
    "next_action": {"label": "Open Topology", "href": "/topology"},
    "followups": [],
    "unknowns": ["2 devices refused credentials, so their state is unknown."],
    "steps": ["Reading the Enterprise Knowledge Graph…",
              "Checking discovery completeness…"],
    "generated_at": "2026-07-30T09:00:00+00:00",
}


class RecordingProvider:
    kind = "recording"
    requests: list = []
    reply = "In plain terms: the Mumbai core device is having trouble."

    def __init__(self, settings) -> None:
        self.settings = settings

    def complete(self, request):
        RecordingProvider.requests.append(request)
        return AIResult(
            text=self.reply, model=request.model, provider=self.kind,
            input_tokens=90, output_tokens=30, latency_ms=11,
        )

    def health(self):
        return ProviderHealth(ok=True, detail="ok")


class DeadProvider(RecordingProvider):
    kind = "dead"

    def complete(self, request):
        raise AIProviderError("connection refused", retryable=False)


class MemoryCredentials:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def save(self, ref: str, secret: str) -> None:
        self.store[ref] = secret

    def get(self, ref: str) -> str:
        return self.store.get(ref, "")

    def delete(self, ref: str) -> None:
        self.store.pop(ref, None)


def registry_with_doubles():
    registry = build_provider_registry()
    for double in (RecordingProvider, DeadProvider):
        registry.register(ProviderDescriptor(
            kind=double.kind, label=double.kind.title(), factory=double,
            hosting="local",
        ))
    return registry


class ExplanationHarness(unittest.TestCase):
    def setUp(self) -> None:
        RecordingProvider.requests = []
        RecordingProvider.reply = (
            "In plain terms: the Mumbai core device is having trouble."
        )

    def service_for(self, tmp, **overrides):
        providers = registry_with_doubles()
        config = PrismConfig(
            enabled=True, provider_kind="recording", model="local-1",
            enabled_capabilities=(
                CAPABILITY_PLAIN_ENGLISH, CAPABILITY_EXECUTIVE_SUMMARY,
                CAPABILITY_TRANSLATION,
            ),
        )
        if overrides:
            config = replace(config, **overrides)
        repository = PrismConfigRepository(
            tmp, credential_provider=MemoryCredentials(), registry=providers
        )
        repository.save(config, now="2026-07-30T00:00:00+00:00")
        return PrismService(
            repository=repository, output_dir=tmp, providers=providers,
            clock=lambda: "2026-07-30T09:30:00+00:00",
        )


# -- Parts 1/2/3: plain english, executive summary, audiences --------------

class ExplanationTests(ExplanationHarness):
    def test_a_plain_english_explanation_is_produced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = explain(
                STORED_ANSWER, service=self.service_for(Path(tmp)),
                audience_key="engineer", now="2026-07-30T09:30:00+00:00",
            )
            self.assertTrue(result.ok, result.reason)
            self.assertEqual(CAPABILITY_PLAIN_ENGLISH, result.capability)
            self.assertEqual("Network engineer", result.audience_label)
            self.assertTrue(result.prompt_version.startswith("plain-english@"))
            self.assertEqual("recording", result.provider)

    def test_manager_and_executive_use_the_executive_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(Path(tmp))
            for key in ("manager", "executive"):
                with self.subTest(audience=key):
                    result = explain(STORED_ANSWER, service=service,
                                     audience_key=key)
                    self.assertTrue(result.ok, result.reason)
                    self.assertEqual(
                        CAPABILITY_EXECUTIVE_SUMMARY, result.capability
                    )

    def test_the_audience_changes_the_reader_not_the_findings(self) -> None:
        """The whole safety story of Part 3: same evidence, same
        numbers, same unknowns — only the described reader differs."""

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(Path(tmp))
            explain(STORED_ANSWER, service=service, audience_key="engineer")
            engineer = RecordingProvider.requests[-1]
            explain(STORED_ANSWER, service=service, audience_key="soc")
            soc = RecordingProvider.requests[-1]

            def user_text(request):
                return request.messages[-1].content

            # The finding block is byte-identical between audiences.
            self.assertEqual(
                user_text(engineer).split("Rewrite it")[0],
                user_text(soc).split("Rewrite it")[0],
            )
            # Only the system prompt's reader differs.
            self.assertIn("network engineer", engineer.messages[0].content)
            self.assertIn("security operations",
                          soc.messages[0].content)

    def test_every_audience_is_offered_a_capability_that_exists(self) -> None:
        for audience in AUDIENCES:
            with self.subTest(audience=audience.key):
                self.assertIn(
                    audience.capability,
                    (CAPABILITY_PLAIN_ENGLISH, CAPABILITY_EXECUTIVE_SUMMARY),
                )
                self.assertTrue(audience.descriptor.strip())

    def test_limitations_always_travel_to_the_model(self) -> None:
        """Atlas's unknowns must reach the prompt: an explanation that
        silently drops them would be hiding uncertainty."""

        with tempfile.TemporaryDirectory() as tmp:
            explain(STORED_ANSWER, service=self.service_for(Path(tmp)),
                    audience_key="executive")
            sent = RecordingProvider.requests[-1].messages[-1].content
            self.assertIn("refused credentials", sent)
            self.assertIn("could not determine", sent.casefold())

    def test_the_stored_confidence_is_passed_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            explain(STORED_ANSWER, service=self.service_for(Path(tmp)))
            sent = RecordingProvider.requests[-1].messages[-1].content
            self.assertIn("Medium", sent)


# -- Part 4: translation ---------------------------------------------------

class TranslationTests(ExplanationHarness):
    def test_a_language_choice_adds_a_translation_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = explain(
                STORED_ANSWER, service=self.service_for(Path(tmp)),
                audience_key="engineer", language="fr",
            )
            self.assertTrue(result.ok, result.reason)
            self.assertTrue(result.translated)
            self.assertEqual("French", result.language_label)
            # Two calls: explain, then translate.
            self.assertEqual(2, len(RecordingProvider.requests))
            self.assertIn("French",
                          RecordingProvider.requests[-1].messages[-1].content)

    def test_english_needs_no_translation_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = explain(STORED_ANSWER,
                             service=self.service_for(Path(tmp)),
                             language="en")
            self.assertFalse(result.translated)
            self.assertEqual(1, len(RecordingProvider.requests))

    def test_an_unknown_language_falls_back_to_english(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = explain(STORED_ANSWER,
                             service=self.service_for(Path(tmp)),
                             language="klingon")
            self.assertEqual("en", result.language)
            self.assertFalse(result.translated)

    def test_a_failed_translation_keeps_the_explanation(self) -> None:
        """Losing the translation must not lose the explanation."""

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(
                Path(tmp),
                enabled_capabilities=(CAPABILITY_PLAIN_ENGLISH,),
            )  # translation capability switched OFF
            result = explain(STORED_ANSWER, service=service, language="hi")
            self.assertTrue(result.ok, result.reason)
            self.assertFalse(result.translated)
            self.assertTrue(result.text)


# -- Parts 7/8: safety and fallback ---------------------------------------

class FallbackTests(ExplanationHarness):
    def test_ai_disabled_refuses_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(Path(tmp), enabled=False)
            result = explain(STORED_ANSWER, service=service)
            self.assertFalse(result.ok)
            self.assertEqual("", result.text)
            self.assertTrue(result.reason)

    def test_a_dead_provider_refuses_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(Path(tmp), provider_kind="dead",
                                       retries=0)
            result = explain(STORED_ANSWER, service=service)
            self.assertFalse(result.ok)
            self.assertEqual("", result.text)

    def test_policy_denial_refuses_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(
                Path(tmp), provider_kind="openai", model="gpt-x",
                allow_cloud_providers=False,
            )
            result = explain(STORED_ANSWER, service=service)
            self.assertFalse(result.ok)
            self.assertEqual([], RecordingProvider.requests)

    def test_a_capability_switched_off_refuses_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(Path(tmp), enabled_capabilities=())
            result = explain(STORED_ANSWER, service=service)
            self.assertFalse(result.ok)

    def test_no_stored_answer_refuses_without_calling_a_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service_for(Path(tmp))
            self.assertFalse(explain(None, service=service).ok)
            self.assertFalse(
                explain({"summary": ""}, service=service).ok
            )
            self.assertEqual([], RecordingProvider.requests)


# -- Part 9: audit ---------------------------------------------------------

class AuditTests(ExplanationHarness):
    def test_explanations_are_audited_without_their_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            RecordingProvider.reply = "SENSITIVE-EXPLANATION-BODY"
            service = self.service_for(root)
            explain(STORED_ANSWER, service=service, audience_key="engineer",
                    language="es")
            from founderos_atlas.prism import UsageLedger

            records = UsageLedger(root).entries()
            # One explanation + one translation, both audited.
            self.assertEqual(2, len(records))
            raw = json.dumps(records)
            self.assertNotIn("SENSITIVE-EXPLANATION-BODY", raw)
            self.assertNotIn("mumbai-core", raw)
            for record in records:
                self.assertTrue(record["capability"])
                self.assertTrue(record["prompt_version"])
                self.assertEqual("recording", record["provider"])
                self.assertIn("latency_ms", record)
                self.assertIn("input_tokens", record)
                self.assertIn("estimated_cost", record)


# -- the finding builder ---------------------------------------------------

class FindingTextTests(unittest.TestCase):
    def test_the_finding_carries_summary_and_evidence_labels(self) -> None:
        text = finding_text(STORED_ANSWER)
        self.assertIn("mumbai-core is degraded", text)
        self.assertIn("Enterprise Graph", text)
        self.assertIn("Change Report", text)

    def test_limitations_are_stated_even_when_absent(self) -> None:
        self.assertIn("no limitations", limitations_text({"unknowns": []}))
        self.assertIn("refused credentials", limitations_text(STORED_ANSWER))

    def test_a_sparse_answer_does_not_raise(self) -> None:
        self.assertEqual("", finding_text({}))
        self.assertTrue(limitations_text({}))


# -- Part 5: the panel -----------------------------------------------------

class PanelContextTests(ExplanationHarness):
    def test_the_panel_is_absent_when_ai_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = panel_context(self.service_for(Path(tmp),
                                                     enabled=False))
            self.assertFalse(context["available"])

    def test_the_panel_offers_only_usable_audiences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = panel_context(self.service_for(
                Path(tmp), enabled_capabilities=(CAPABILITY_PLAIN_ENGLISH,),
            ))
            self.assertTrue(context["available"])
            offered = {item["key"] for item in context["audiences"]}
            self.assertIn("engineer", offered)
            # Executive audiences need the executive-summary capability.
            self.assertNotIn("executive", offered)
            self.assertFalse(context["translation"])

    def test_languages_are_offered_with_english_first(self) -> None:
        self.assertEqual("en", LANGUAGES[0][0])
        self.assertEqual("engineer", DEFAULT_AUDIENCE.key)


# -- the web surface -------------------------------------------------------

class AdvisorAIPageTests(unittest.TestCase):
    def build_client(self, workdir: Path):
        from tests.test_polish import build_world

        _, client = build_world(workdir)
        return client

    def enable_ai(self, client) -> None:
        client.post("/settings/ai", data={
            "enabled": "1", "provider_kind": "ollama", "model": "llama3",
            "endpoint": "http://127.0.0.1:11434/v1",
            "enabled_capabilities": [
                CAPABILITY_PLAIN_ENGLISH, CAPABILITY_EXECUTIVE_SUMMARY,
                CAPABILITY_TRANSLATION,
            ],
            "redaction_rules": ["ip-addresses", "hostnames"],
            "timeout_seconds": "2", "retries": "0",
            "max_context_tokens": "8192", "max_output_tokens": "400",
            "temperature": "0.2", "currency": "USD", "verify_tls": "1",
        }, follow_redirects=True)

    def test_the_panel_is_absent_until_ai_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/advisor/ask", data={"question": "Find GW"},
                        follow_redirects=True)
            page = client.get("/advisor").data
            self.assertNotIn(b"advisor-ai-panel", page)
            # Atlas's own answer is present regardless.
            self.assertIn(b"advisor-response", page)

    def test_the_panel_appears_when_ai_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable_ai(client)
            client.post("/advisor/ask", data={"question": "Find GW"},
                        follow_redirects=True)
            page = client.get("/advisor").data
            self.assertIn(b"advisor-ai-panel", page)
            self.assertIn(b"PRISM Views", page)
            self.assertIn(b"Atlas determines. PRISM explains.", page)
            self.assertIn(b"source of truth", page)
            self.assertIn(b'id="advisor-ai-audience"', page)

    def test_the_explain_endpoint_never_errors_when_ai_is_off(self) -> None:
        """Part 8: the page asks, the platform declines, and the answer
        is a calm 200 — not a 500 the browser has to interpret."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/advisor/ask", data={"question": "Find GW"},
                        follow_redirects=True)
            response = client.post("/api/advisor/explain",
                                   json={"conversation": 0})
            self.assertEqual(200, response.status_code)
            payload = response.get_json()
            self.assertFalse(payload["ok"])
            self.assertEqual("", payload["text"])

    def test_explaining_a_missing_conversation_is_handled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            response = client.post("/api/advisor/explain",
                                   json={"conversation": 99})
            self.assertEqual(200, response.status_code)
            self.assertFalse(response.get_json()["ok"])

    def test_a_malformed_body_is_refused_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            response = client.post(
                "/api/advisor/explain", data=b"[1,2]",
                content_type="application/json",
            )
            self.assertEqual(400, response.status_code)

    def test_atlas_answer_is_unchanged_by_the_panel(self) -> None:
        """The success criterion: enabling AI must not alter one word of
        Atlas's own deterministic output."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/advisor/ask", data={"question": "Find GW"},
                        follow_redirects=True)
            before = client.get("/advisor").data
            answer_before = before[before.index(b"advisor-response"):
                                   before.index(b"Recent Conversations")]
            self.enable_ai(client)
            after = client.get("/advisor").data
            answer_after = after[after.index(b"advisor-response"):
                                 after.index(b"advisor-ai-panel")]
            self.assertIn(b"Found GW", answer_before)
            self.assertIn(b"Found GW", answer_after)
            # The verdict, confidence and evidence blocks are identical.
            for marker in (b"Inventory summary</h2>", b"<h2>Evidence</h2>",
                           b"Answer confidence</h3>"):
                self.assertIn(marker, answer_before)
                self.assertIn(marker, answer_after)


if __name__ == "__main__":
    unittest.main()
