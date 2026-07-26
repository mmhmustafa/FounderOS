"""Focused regression contracts for the post-PR-154 stabilization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.workspace import AdministrationRepository
from tests.test_polish import build_world


ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "src/founderos_atlas/visualization/templates/topology.html"
DEVICE = ROOT / "src/founderos_atlas/web/templates/device.html"


class TopologyViewerStabilizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.viewer = VIEWER.read_text(encoding="utf-8")

    def test_cytoscape_uses_attached_element_and_default_wheel_contract(self):
        self.assertIn("graphContainer instanceof HTMLElement", self.viewer)
        self.assertIn("graphContainer.isConnected", self.viewer)
        self.assertNotIn("wheelSensitivity:", self.viewer)
        self.assertIn('id="zoom-out"', self.viewer)
        self.assertIn('id="zoom-in"', self.viewer)

    def test_compact_toolbar_has_accessible_overflow_at_tablet_and_phone(self):
        self.assertIn("@media (max-width: 900px)", self.viewer)
        self.assertIn("@media (max-width: 480px)", self.viewer)
        self.assertIn('id="toolbar-more-toggle"', self.viewer)
        self.assertIn('aria-controls="toolbar-secondary"', self.viewer)
        self.assertIn("toolbarSecondary.classList.toggle('is-open'", self.viewer)
        self.assertNotIn("onclick=", self.viewer.casefold())

    def test_simple_device_view_cannot_render_credential_reference(self):
        template = DEVICE.read_text(encoding="utf-8")
        self.assertIn(
            "display_level == 'expert' and can('credentials.manage')",
            template,
        )
        self.assertNotIn(
            "{% if device.credential_ref %}<li><span>Credential</span>",
            template,
        )


class DeferredTopologySupportTests(unittest.TestCase):
    def test_initial_graph_defers_large_supporting_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            initial = client.get("/topology?scope=all").get_data(as_text=True)
            loaded = client.get(
                "/topology?scope=all&support=1"
            ).get_data(as_text=True)

            self.assertIn("Load topology facts", initial)
            self.assertNotIn('aria-label="Device inventory"', initial)
            self.assertNotIn('aria-label="Unresolved peer identities"', initial)
            self.assertIn('aria-label="Device inventory"', loaded)
            self.assertIn("Hide supporting data", loaded)
            self.assertLess(len(initial), len(loaded))

    def test_inventory_pages_stay_bounded_at_representative_estate_sizes(self):
        from founderos_atlas.web.pagination import paginate

        for size in (117, 500, 1_000, 5_000):
            with self.subTest(size=size):
                first = paginate(list(range(size)), page_size=50)
                last = paginate(
                    list(range(size)),
                    requested_page=first.page_count,
                    page_size=50,
                )
                self.assertEqual(size, first.total)
                self.assertLessEqual(len(first.items), 50)
                self.assertLessEqual(len(last.items), 50)
                self.assertEqual(size - 1, last.items[-1])


class DiscoveryDraftHygieneTests(unittest.TestCase):
    def test_expired_drafts_archive_but_recent_and_running_drafts_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = AdministrationRepository(Path(tmp))
            now = datetime(2026, 7, 26, tzinfo=timezone.utc)
            old = repository.save_draft(None, {"name": "Old"})
            recent = repository.save_draft(None, {"name": "Recent"})
            running = repository.save_draft(
                None, {"name": "Running", "status": "running"}
            )
            state = repository.drafts()
            state[old]["updated_at"] = (
                now - timedelta(days=31)
            ).isoformat()
            state[recent]["updated_at"] = (
                now - timedelta(days=2)
            ).isoformat()
            state[running]["updated_at"] = (
                now - timedelta(days=31)
            ).isoformat()
            # Use the repository's atomic format to seed deterministic ages.
            repository.drafts_path.write_text(
                json.dumps(
                    {"schema_version": "1.0.0", "drafts": state}
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                1, repository.archive_expired_drafts(30, now=now)
            )
            archived = repository.drafts()
            self.assertTrue(archived[old]["archived"])
            self.assertFalse(bool(archived[recent].get("archived")))
            self.assertFalse(bool(archived[running].get("archived")))

    def test_archive_cleanup_preserves_open_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = AdministrationRepository(Path(tmp))
            first = repository.save_draft(None, {"name": "First"})
            second = repository.save_draft(None, {"name": "Second"})
            state = repository.drafts()
            state[first]["archived"] = True
            state[second]["archived"] = True
            repository.drafts_path.write_text(
                json.dumps(
                    {"schema_version": "1.0.0", "drafts": state}
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                1, repository.delete_archived_drafts(except_id=second)
            )
            self.assertNotIn(first, repository.drafts())
            self.assertIn(second, repository.drafts())

    def test_wizard_shows_only_three_recent_drafts_until_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir, discover=False)
            repository = AdministrationRepository(workdir / "workspace")
            for number in range(5):
                repository.save_draft(None, {"name": f"Draft {number}"})

            recent = client.get("/discovery/wizard").get_data(as_text=True)
            all_drafts = client.get(
                "/discovery/wizard?show_drafts=all"
            ).get_data(as_text=True)
            self.assertEqual(1, recent.count("Draft 4"))
            self.assertNotIn("Draft 0", recent)
            self.assertIn("View all drafts (5)", recent)
            self.assertIn("Draft 0", all_drafts)
            self.assertIn("Saved discovery drafts", all_drafts)


class HomeCleanupTests(unittest.TestCase):
    def test_first_recommendation_action_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/?scope=all").get_data(as_text=True)
            attention = page.split("Needs your attention", 1)[1].split(
                "</section>", 1
            )[0]
            self.assertNotIn(">warning<", attention.casefold())
            self.assertIn("Needs review", attention)


if __name__ == "__main__":
    unittest.main()
