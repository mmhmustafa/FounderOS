"""PRISM Views: the rename, the Playground, and the philosophy.

Atlas determines. PRISM explains. These tests defend that separation:
the rename is complete, an operator's existing configuration and API key
survive it, the Playground never touches enterprise evidence, and Atlas
findings stay byte-identical whatever PRISM does with them.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from founderos_atlas.advisor.explanation import AUDIENCES
from founderos_atlas.prism import (
    PRISM_FILENAME,
    USAGE_FILENAME,
    PrismConfig,
    PrismConfigRepository,
    credential_ref_for,
)
from founderos_atlas.prism.config import (
    LEGACY_CREDENTIAL_REF_PREFIX,
    LEGACY_DOCUMENT_KEY,
    LEGACY_FILENAME,
)

REPO = Path(__file__).resolve().parent.parent
# Directories that hold shipped source, docs and tests — not runtime
# data, caches or the developer's own captured evidence.
SCANNED = (
    REPO / "src" / "founderos_atlas",
    REPO / "docs",
    REPO / "tests",
)
SCANNED_SUFFIXES = {".py", ".md", ".html", ".js", ".css"}
LEGACY_NAME = re.compile(r"[Oo]racle|ORACLE")  # RENAME-EXEMPT (detector)

# A line carrying this sentinel is allowed to name the old product.
# Only two things may: this detector, and the migration constants that
# stop the rename orphaning an operator's stored API key.
EXEMPT = "RENAME-EXEMPT"


class MemoryCredentials:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def save(self, ref: str, secret: str) -> None:
        self.store[ref] = secret

    def get(self, ref: str) -> str:
        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
        )

        if ref not in self.store:
            # Mirror the keyring provider, which RAISES for a missing
            # ref rather than returning "" — the migration has to work
            # against the store that actually needs it.
            raise CredentialNotFoundError("no stored credential")
        return self.store[ref]

    def delete(self, ref: str) -> None:
        self.store.pop(ref, None)


class RenameCompletenessTests(unittest.TestCase):
    """Part 1: the rename is complete — no trace of the old name."""

    def test_no_source_doc_or_test_mentions_the_old_name(self) -> None:
        offenders: list[str] = []
        for root in SCANNED:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                    continue
                if "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for number, line in enumerate(text.splitlines(), start=1):
                    if not LEGACY_NAME.search(line) or EXEMPT in line:
                        continue
                    offenders.append(
                        f"{path.relative_to(REPO)}:{number}: {line.strip()}"
                    )
        self.assertEqual(
            [], offenders, "references to the old product name remain"
        )

    def test_the_package_and_artifacts_are_named_prism(self) -> None:
        self.assertTrue((REPO / "src/founderos_atlas/prism").is_dir())
        old_package = "src/founderos_atlas/oracle"  # RENAME-EXEMPT
        self.assertFalse((REPO / old_package).exists())
        self.assertEqual("prism.json", PRISM_FILENAME)
        self.assertEqual("prism-usage.jsonl", USAGE_FILENAME)
        self.assertTrue(credential_ref_for("openai").startswith("atlas-prism"))

    def test_the_platform_documentation_exists_under_its_new_name(
        self,
    ) -> None:
        self.assertTrue((REPO / "docs/ATLAS_PRISM_PLATFORM.md").is_file())
        old_doc = "docs/ATLAS_ORACLE_AI_PLATFORM.md"  # RENAME-EXEMPT
        self.assertFalse((REPO / old_doc).exists())

    def test_the_philosophy_is_documented(self) -> None:
        """Part 2: the separation must be stated, not implied."""

        text = (REPO / "docs/ATLAS_PRISM_PLATFORM.md").read_text(
            encoding="utf-8"
        )
        for claim in (
            "Atlas determines", "PRISM explains",
            "Evidence Presentation Platform",
            "never invents",
        ):
            self.assertIn(claim, text)


class LegacyMigrationTests(unittest.TestCase):
    """The rename must not cost an operator their configuration."""

    def test_a_legacy_config_file_is_still_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_document = (
                '{"schema_version": "1.0.0", "%s": '
                '{"enabled": true, "provider_kind": "ollama", '
                '"model": "llama3"}}' % LEGACY_DOCUMENT_KEY
            )
            (root / LEGACY_FILENAME).write_text(
                legacy_document, encoding="utf-8"
            )
            config = PrismConfigRepository(
                root, credential_provider=MemoryCredentials()
            ).load()
            self.assertTrue(config.enabled)
            self.assertEqual("llama3", config.model)

    def test_a_legacy_api_key_migrates_to_the_new_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            credentials = MemoryCredentials()
            credentials.store[f"{LEGACY_CREDENTIAL_REF_PREFIX}:openrouter"] = (
                "sk-or-carried-over"
            )
            repository = PrismConfigRepository(
                tmp, credential_provider=credentials
            )
            self.assertTrue(repository.has_api_key("openrouter"))
            # Moved, not copied: nothing is left under the old name.
            self.assertEqual(
                "sk-or-carried-over",
                credentials.store[credential_ref_for("openrouter")],
            )
            self.assertNotIn(
                f"{LEGACY_CREDENTIAL_REF_PREFIX}:openrouter",
                credentials.store,
            )

    def test_api_key_reads_through_the_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            credentials = MemoryCredentials()
            credentials.store[f"{LEGACY_CREDENTIAL_REF_PREFIX}:openai"] = (
                "sk-legacy"
            )
            repository = PrismConfigRepository(
                tmp, credential_provider=credentials
            )
            self.assertEqual("sk-legacy", repository.api_key("openai"))

    def test_removing_a_key_removes_both_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            credentials = MemoryCredentials()
            credentials.store[credential_ref_for("openai")] = "new"
            credentials.store[f"{LEGACY_CREDENTIAL_REF_PREFIX}:openai"] = "old"
            PrismConfigRepository(
                tmp, credential_provider=credentials
            ).delete_api_key("openai")
            self.assertEqual({}, credentials.store)

    def test_a_fresh_workspace_reports_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = PrismConfigRepository(
                tmp, credential_provider=MemoryCredentials()
            )
            self.assertFalse(repository.has_api_key("openai"))
            self.assertEqual("", repository.api_key("openai"))


class PresentationModeTests(unittest.TestCase):
    """Parts 3 and 6: the audiences PRISM offers."""

    def test_every_documented_audience_exists(self) -> None:
        keys = {audience.key for audience in AUDIENCES}
        for expected in ("engineer", "junior", "soc", "operations",
                         "manager", "executive"):
            self.assertIn(expected, keys)

    def test_each_audience_describes_a_reader_not_a_conclusion(self) -> None:
        """A descriptor that told the model what to CONCLUDE would make
        the audience change the findings."""

        banned = ("conclude", "decide", "assume", "estimate that",
                  "you should say")
        for audience in AUDIENCES:
            with self.subTest(audience=audience.key):
                lowered = audience.descriptor.casefold()
                for phrase in banned:
                    self.assertNotIn(phrase, lowered)


class PlaygroundTests(unittest.TestCase):
    """Part 8: the demonstration environment."""

    def build_client(self, workdir: Path):
        from tests.test_polish import build_world

        _, client = build_world(workdir)
        return client

    def test_the_playground_explains_itself_when_prism_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self.build_client(Path(tmp)).get(
                "/prism/playground"
            ).data
            self.assertIn(b"PRISM Playground", page)
            self.assertIn(b"PRISM is not ready yet", page)
            self.assertIn(b"Atlas itself is unaffected", page)

    def test_the_playground_never_reads_enterprise_evidence(self) -> None:
        """It presents PASTED text. A demonstration that quietly used
        real evidence would be a privacy surprise, and a bad view there
        could be mistaken for an Atlas conclusion."""

        source = (
            REPO / "src/founderos_atlas/web/routes.py"
        ).read_text(encoding="utf-8")
        block = source.split("def prism_playground()", 1)[1].split(
            "@app.route", 1
        )[0]
        self.assertIn("evidence-FREE", block)
        # It builds its finding from the form, never from a repository.
        self.assertIn('request.form.get("evidence")', block)
        self.assertNotIn("advisor_repository()", block)

    def test_the_page_offers_every_audience_and_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": "ollama",
                "model": "llama3", "endpoint": "http://127.0.0.1:11434/v1",
                "enabled_capabilities": [
                    "plain-english", "executive-summary", "translation",
                ],
                "redaction_rules": ["ip-addresses", "hostnames"],
                "timeout_seconds": "2", "retries": "0",
                "max_context_tokens": "8192", "max_output_tokens": "400",
                "temperature": "0.2", "currency": "USD", "verify_tls": "1",
            }, follow_redirects=True)
            page = client.get("/prism/playground").data
            self.assertIn(b"Atlas evidence", page)
            self.assertIn(b"Junior engineer", page)
            self.assertIn(b"Executive", page)
            self.assertIn(b"Compare all audiences", page)
            self.assertNotIn(b"PRISM is not ready yet", page)

    def test_pasted_evidence_is_redacted_before_any_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": "ollama",
                "model": "llama3", "endpoint": "http://127.0.0.1:9/v1",
                "enabled_capabilities": ["plain-english"],
                "redaction_rules": ["ip-addresses", "hostnames"],
                "timeout_seconds": "1", "retries": "0",
                "max_context_tokens": "8192", "max_output_tokens": "200",
                "temperature": "0.2", "currency": "USD", "verify_tls": "1",
            }, follow_redirects=True)
            page = client.post("/prism/playground", data={
                "action": "generate",
                "evidence": "core1 at 10.9.9.9 snmp-server community S3cret",
                "audience": "engineer", "language": "en",
                "confidence": "Medium", "limitations": "",
            }).data.decode("utf-8")
            self.assertIn("Data sent to the provider", page)
            # Scope the check to the PAYLOAD blockquote. Both the
            # textarea and stage 1 legitimately echo the operator's own
            # paste back to them — stage 1 exists precisely to show the
            # untouched original. What matters is the text that would
            # leave Atlas, which is stage 3 and nothing else.
            preview = page.split("Data sent to the provider", 1)[1]
            preview = preview.split("</blockquote>", 1)[0]
            self.assertNotIn("S3cret", preview)
            self.assertNotIn("10.9.9.9", preview)
            self.assertIn("[redacted:", preview)

    def test_the_preview_matches_what_is_actually_sent(self) -> None:
        """The preview and the real call must redact identically.

        They were computed from different name lists once, and the
        preview showed hostnames redacted that the provider received in
        the clear. A preview that overstates protection is worse than no
        preview at all, because an administrator trusts it.

        This is the STRUCTURAL half of that guarantee: one name list and
        one alias book must reach both paths. The behavioural half —
        the preview text appearing verbatim in the recorded payload,
        under every privacy profile — is
        ``test_prism_semantic.PreviewMatchesWhatIsSentTests``.
        """

        source = (
            REPO / "src/founderos_atlas/web/routes.py"
        ).read_text(encoding="utf-8")
        block = source.split("def prism_playground()", 1)[1].split(
            "@app.route", 1
        )[0]
        # ONE name list, feeding both the redact() preview and explain().
        self.assertIn("known_names = _enterprise_names(", block)
        self.assertIn("known_names_for(book, known_names)", block)
        self.assertIn("known_names=known_names", block)
        self.assertNotIn("known_names=()", block)
        # PR-166.2 added a second thing that must match: the alias book.
        # A preview aliased from one book while the provider is sent
        # another would mislead in exactly the same way.
        self.assertIn("book = _alias_book(", block)
        self.assertIn("aliases=book)", block)          # the preview
        self.assertIn("aliases=side_book", block)      # the real call
        # ...and the side's book must be built for the profile of the
        # service that will USE it. Comparison overrides the provider,
        # which under "match the provider" changes the profile too; one
        # shared book let a cloud side run with an Internal book and no
        # known names at all, sending hostnames in the clear.
        self.assertIn("target.config.active_profile()", block)

    def test_a_dead_provider_leaves_the_page_usable(self) -> None:
        """Part 11 on the Playground too: the pasted evidence stays and
        the failure is stated calmly."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": "openai-compatible",
                "model": "nope", "endpoint": "http://127.0.0.1:9/v1",
                "enabled_capabilities": ["plain-english"],
                "redaction_rules": ["ip-addresses"],
                "timeout_seconds": "1", "retries": "0",
                "max_context_tokens": "8192", "max_output_tokens": "200",
                "temperature": "0.2", "currency": "USD", "verify_tls": "1",
            }, follow_redirects=True)
            response = client.post("/prism/playground", data={
                "action": "generate", "evidence": "a finding",
                "audience": "engineer", "language": "en",
                "confidence": "High", "limitations": "",
            })
            self.assertEqual(200, response.status_code)
            page = response.data.decode("utf-8")
            self.assertIn("could not generate this view", page)
            self.assertIn("a finding", page)  # the paste survives


class AdvisorPanelBrandingTests(unittest.TestCase):
    """Part 4: an operator must see which content is which."""

    def test_the_panel_names_prism_and_separates_it_from_atlas(
        self,
    ) -> None:
        template = (
            REPO / "src/founderos_atlas/web/templates/advisor.html"
        ).read_text(encoding="utf-8")
        panel = template.split('id="advisor-ai-panel"', 1)[1]
        self.assertIn("PRISM Views", panel)
        self.assertIn("Atlas determines. PRISM explains.", panel)
        self.assertIn("source of truth", panel)
        self.assertIn("Generated by PRISM", panel)


if __name__ == "__main__":
    unittest.main()
