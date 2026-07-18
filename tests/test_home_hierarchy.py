"""Home/Overview hierarchy (PR: attention-first Home).

The page answers "does anything require my attention?" — canonical
state first, top issues with filtered links, one dominant primary
action, metrics one disclosure away in Simple and inline above Expert.
Unknown is stated as unknown, never dressed as healthy.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


def _at_level(client, level: str) -> None:
    client.post("/preferences/display-level", data={"display_level": level})


class HomeHierarchyTests(unittest.TestCase):
    def test_no_discovery_states_unknown_with_first_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("Network state is unknown", page)
            self.assertIn("no discovery has run yet", page)
            self.assertIn("Run your first discovery", page)
            # Unknown is never dressed as healthy.
            self.assertNotIn("status-healthy", page)

    def test_simple_keeps_metrics_one_disclosure_away(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _at_level(client, "simple")
            page = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("Enterprise metrics", page)     # reachable
            self.assertNotIn("<h2>Enterprise Health</h2>", page)  # not inline
            self.assertIn("All workflows", page)
            # The canonical counts are still IN the page, just collapsed.
            self.assertIn("Canonical devices", page)

    def test_expert_keeps_metrics_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _at_level(client, "expert")
            page = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("<h2>Enterprise Health</h2>", page)
            self.assertIn("What would you like to do?", page)

    def test_exactly_one_primary_action_in_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for level in ("simple", "detailed", "expert"):
                _at_level(client, level)
                page = client.get("/?scope=all").get_data(as_text=True)
                content = page.split('id="atlas-main"')[1]
                self.assertEqual(
                    1, content.count("btn btn-primary"),
                    f"{level}: the page must have ONE dominant action",
                )

    def test_attention_items_link_to_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("Needs your attention", page)
            section = page.split("Needs your attention")[1].split("</section>")[0]
            self.assertIn('href="', section)
            self.assertIn("Evidence:", section)


class TopologyCalmDefaultsTests(unittest.TestCase):
    def test_simple_summarizes_and_collapses_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _at_level(client, "simple")
            page = client.get("/topology?scope=all").get_data(as_text=True)
            self.assertIn("Topology facts and evidence", page)
            self.assertIn("relationship(s)", page)
            # Full tables still present, one disclosure away.
            self.assertIn("Inter-site links", page)

    def test_expert_keeps_facts_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _at_level(client, "expert")
            page = client.get("/topology?scope=all").get_data(as_text=True)
            self.assertNotIn("Topology facts and evidence</summary>", page)
            self.assertIn("Inter-site links", page)


if __name__ == "__main__":
    unittest.main()
