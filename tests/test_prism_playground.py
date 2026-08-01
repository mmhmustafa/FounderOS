"""PR-166.1: PRISM Playground enhancements.

Sample case library, side-by-side comparison, and export. The property
that matters throughout: the Atlas evidence is identical across every
view and every export — only PRISM's presentation of it changes.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from founderos_atlas.prism.export import (
    EXPORT_FORMATS,
    PROVENANCE_STATEMENT,
    as_markdown,
    as_pdf,
    as_text,
    render,
)
from founderos_atlas.prism.samples import (
    SAMPLE_BY_KEY,
    SAMPLE_CASES,
    sample,
    sample_choices,
)

VIEW = {
    "ok": True,
    "text": "In plain terms: the core device lost its BGP session.",
    "audience_label": "Network engineer", "language_label": "English",
    "capability": "plain-english", "provider": "openrouter",
    "model": "openai/gpt-oss-20b:free",
    "prompt_version": "plain-english@1.1.0",
    "generated_at": "2026-07-31T09:00:00+00:00",
    "latency_ms": 20628, "input_tokens": 499, "output_tokens": 259,
    "estimated_cost": 0.0021, "redaction_summary": "2 hostname, 1 ip",
    "translated": False,
}
FAILED_VIEW = {"ok": False, "audience_label": "Executive",
               "language_label": "English"}
EVIDENCE = "mumbai-core cannot reach chennai-edge: eBGP session Idle 47m."


# -- Part 1: the sample library --------------------------------------------

class SampleLibraryTests(unittest.TestCase):
    def test_the_documented_cases_are_all_present(self) -> None:
        labels = {case.label for case in SAMPLE_CASES}
        for expected in (
            "BGP session down", "OSPF neighbour failure", "Interface down",
            "ACL blocking traffic", "VPN tunnel failure", "High CPU",
            "Memory exhaustion", "Port flapping", "STP topology change",
            "HSRP failover", "Routing loop", "Packet loss investigation",
        ):
            self.assertIn(expected, labels)
        self.assertEqual(12, len(SAMPLE_CASES))

    def test_every_sample_states_what_atlas_could_not_determine(
        self,
    ) -> None:
        """A sample without limitations would demonstrate PRISM against
        a version of Atlas that does not exist."""

        for case in SAMPLE_CASES:
            with self.subTest(case=case.key):
                self.assertTrue(case.limitations.strip())
                self.assertGreater(len(case.limitations), 40)

    def test_every_sample_reads_like_a_real_atlas_answer(self) -> None:
        for case in SAMPLE_CASES:
            with self.subTest(case=case.key):
                self.assertIn("Evidence Atlas cited:", case.evidence)
                self.assertIn("Checks Atlas performed:", case.evidence)
                self.assertIn(
                    case.confidence, ("High", "Medium", "Low", "Unknown")
                )
                self.assertTrue(case.category.strip())

    def test_confidence_varies_across_the_library(self) -> None:
        """All-High samples would misrepresent how Atlas actually
        answers; real investigations differ in certainty."""

        levels = {case.confidence for case in SAMPLE_CASES}
        self.assertGreaterEqual(len(levels), 3)

    def test_keys_are_unique_and_addressable(self) -> None:
        keys = [case.key for case in SAMPLE_CASES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), len(SAMPLE_BY_KEY))
        self.assertIsNotNone(sample("bgp-session-down"))
        self.assertIsNone(sample("not-a-case"))
        self.assertEqual(len(SAMPLE_CASES), len(sample_choices()))


# -- Part 3: export --------------------------------------------------------

class ExportTests(unittest.TestCase):
    def test_markdown_carries_evidence_views_and_provenance(self) -> None:
        text = as_markdown([VIEW, FAILED_VIEW], evidence=EVIDENCE,
                           generated_at="2026-07-31T09:05:00+00:00")
        self.assertIn(EVIDENCE, text)
        self.assertIn(VIEW["text"], text)
        self.assertIn("plain-english@1.1.0", text)
        self.assertIn("openai/gpt-oss-20b:free", text)
        self.assertIn(PROVENANCE_STATEMENT, text)
        # A view that failed is stated, not silently dropped.
        self.assertIn("could not generate", text)

    def test_plain_text_carries_the_same_facts(self) -> None:
        text = as_text([VIEW], evidence=EVIDENCE,
                       generated_at="2026-07-31T09:05:00+00:00")
        self.assertIn(EVIDENCE, text)
        self.assertIn("plain-english@1.1.0", text)
        self.assertIn(PROVENANCE_STATEMENT, text)

    def test_pdf_is_structurally_valid(self) -> None:
        payload = as_pdf([VIEW], evidence=EVIDENCE,
                         generated_at="2026-07-31T09:05:00+00:00")
        self.assertTrue(payload.startswith(b"%PDF-1.4"))
        self.assertTrue(payload.rstrip().endswith(b"%%EOF"))
        for marker in (b"/Type /Catalog", b"/Type /Pages", b"/Type /Page",
                       b"xref", b"trailer", b"startxref"):
            self.assertIn(marker, payload)

    def test_pdf_handles_long_text_and_non_latin_safely(self) -> None:
        """A model may return anything; an export must not corrupt."""

        wide = dict(VIEW, text="Ünïcødé " + ("word " * 400))
        payload = as_pdf([wide], evidence=EVIDENCE * 40,
                         generated_at="2026-07-31T09:05:00+00:00")
        self.assertTrue(payload.startswith(b"%PDF-1.4"))
        # Multi-page: more than one page object was emitted.
        self.assertGreater(payload.count(b"/Type /Page\n")
                           + payload.count(b"/Type /Page "), 1)

    def test_no_sensitive_material_is_exported(self) -> None:
        """Only the metadata shown on screen — never keys, endpoints or
        internal identifiers, even if a caller puts them in the view."""

        sneaky = dict(
            VIEW, api_key="sk-should-not-appear",
            endpoint="https://internal.example/v1",
            credential_ref="atlas-prism:openrouter",
        )
        for fmt in ("md", "txt"):
            payload, _, _ = render(
                fmt, [sneaky], evidence=EVIDENCE,
                generated_at="2026-07-31T09:05:00+00:00",
            )
            text = payload.decode("utf-8")
            with self.subTest(fmt=fmt):
                self.assertNotIn("sk-should-not-appear", text)
                self.assertNotIn("internal.example", text)
                self.assertNotIn("atlas-prism:openrouter", text)

    def test_every_format_declares_its_type_and_filename(self) -> None:
        for fmt in EXPORT_FORMATS:
            with self.subTest(fmt=fmt):
                payload, content_type, filename = render(
                    fmt, [VIEW], evidence=EVIDENCE,
                    generated_at="2026-07-31T09:05:00+00:00",
                )
                self.assertTrue(payload)
                self.assertTrue(content_type)
                self.assertTrue(filename.endswith(f".{fmt}"))


# -- the web surface -------------------------------------------------------

class PlaygroundEnhancementTests(unittest.TestCase):
    def build_client(self, workdir: Path):
        from tests.test_polish import build_world

        _, client = build_world(workdir)
        return client

    def enable(self, client, *, provider="openai-compatible",
               endpoint="http://127.0.0.1:9/v1") -> None:
        client.post("/settings/ai", data={
            "enabled": "1", "provider_kind": provider, "model": "m",
            "endpoint": endpoint,
            "enabled_capabilities": ["plain-english", "executive-summary",
                                     "translation"],
            "redaction_rules": ["ip-addresses", "hostnames"],
            "timeout_seconds": "1", "retries": "0",
            "max_context_tokens": "8192", "max_output_tokens": "200",
            "temperature": "0.2", "currency": "USD", "verify_tls": "1",
        }, follow_redirects=True)

    def test_the_selector_offers_every_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            page = client.get("/prism/playground").data.decode("utf-8")
            self.assertIn('name="sample"', page)
            for case in SAMPLE_CASES:
                self.assertIn(case.label, page)

    def test_loading_a_sample_fills_every_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            page = client.post("/prism/playground", data={
                "action": "sample", "sample": "routing-loop", "evidence": "",
            }).data.decode("utf-8")
            case = sample("routing-loop")
            self.assertIn("10.55.12.0/24", page)          # the evidence
            self.assertIn("not present anywhere", page)   # the limitation
            self.assertIn("Sample case:", page)           # flagged as sample
            self.assertIn(case.label, page)

    def test_a_loaded_sample_remains_editable(self) -> None:
        """The textarea carries the sample text, not a locked fixture,
        and editing it drops the sample flag."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            edited = client.post("/prism/playground", data={
                "action": "generate", "sample": "routing-loop",
                "evidence": "my own edited finding about core1",
                "audience": "engineer", "language": "en",
                "confidence": "High", "limitations": "",
            }).data.decode("utf-8")
            self.assertIn("my own edited finding about core1", edited)
            self.assertNotIn("Sample case:", edited)

    def test_comparison_renders_two_sides_from_one_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            page = client.post("/prism/playground", data={
                "action": "compare-two",
                "evidence": "core1 is unreachable from the branch",
                "audience": "engineer", "language": "en",
                "confidence": "High", "limitations": "",
                "audience_b": "executive", "language_b": "",
                "provider_b": "", "model_b": "",
            }).data.decode("utf-8")
            self.assertEqual(2, page.count('class="prism-view"'))
            self.assertIn('class="prism-compare"', page)
            self.assertIn("identical Atlas evidence", page)

    def test_comparing_all_audiences_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            page = client.post("/prism/playground", data={
                "action": "compare", "evidence": "a finding",
                "audience": "engineer", "language": "en",
                "confidence": "High", "limitations": "",
            }).data.decode("utf-8")
            self.assertEqual(6, page.count('class="prism-view"'))

    def test_export_returns_a_download_in_every_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            payload = json.dumps([VIEW])
            for fmt, expected in (("md", b"# Atlas evidence"),
                                  ("txt", b"ATLAS EVIDENCE"),
                                  ("pdf", b"%PDF-1.4")):
                with self.subTest(fmt=fmt):
                    response = client.post(
                        "/prism/playground/export",
                        data={"format": fmt, "views": payload,
                              "evidence": EVIDENCE},
                    )
                    self.assertEqual(200, response.status_code)
                    self.assertIn(
                        f'filename="prism-view.{fmt}"',
                        response.headers["Content-Disposition"],
                    )
                    self.assertTrue(response.data.startswith(expected))

    def test_export_never_calls_a_provider_again(self) -> None:
        """Exporting renders what was already shown. Re-generating could
        produce different text than the operator read, and would cost a
        second call for a download."""

        from founderos_atlas.prism import UsageLedger

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            self.enable(client)
            before = len(UsageLedger(workdir).entries())
            client.post("/prism/playground/export", data={
                "format": "md", "views": json.dumps([VIEW]),
                "evidence": EVIDENCE,
            })
            self.assertEqual(before, len(UsageLedger(workdir).entries()))

    def test_export_refuses_unknown_formats_and_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            self.assertEqual(400, client.post(
                "/prism/playground/export",
                data={"format": "docx", "views": json.dumps([VIEW]),
                      "evidence": EVIDENCE},
            ).status_code)
            # Nothing to export redirects with a flash, not a download.
            empty = client.post("/prism/playground/export", data={
                "format": "md", "views": "", "evidence": EVIDENCE,
            })
            self.assertEqual(302, empty.status_code)

    def test_oversized_export_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            self.enable(client)
            self.assertEqual(400, client.post(
                "/prism/playground/export",
                data={"format": "md", "views": "x" * 200_001,
                      "evidence": EVIDENCE},
            ).status_code)

    def test_export_is_audited_without_its_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            self.enable(client)
            client.post("/prism/playground/export", data={
                "format": "md", "views": json.dumps([VIEW]),
                "evidence": EVIDENCE,
            })
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("prism-export", audit)
            self.assertNotIn(VIEW["text"], audit)


if __name__ == "__main__":
    unittest.main()
