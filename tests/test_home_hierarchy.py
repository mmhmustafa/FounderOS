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




class HealthAttentionConsistencyTests(unittest.TestCase):
    """Audit-2 High #2: Home may never contradict canonical health."""

    def test_degraded_dimensions_produce_attention_items(self) -> None:
        # build_world collects no configurations: evidence coverage is
        # Degraded — the exact live contradiction (Degraded banner over
        # "Nothing needs your attention").
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/?scope=all").get_data(as_text=True)
            if "status-degraded" in page or "status-critical" in page:
                self.assertNotIn("Nothing needs your attention", page)
                section = page.split("Needs your attention")[1].split(
                    "</section>"
                )[0]
                self.assertIn("Evidence coverage", section)
                self.assertIn('href="/configuration?scope=all"', section)
                self.assertIn("badge-warning", section)

    def test_attention_mapping_per_state(self) -> None:
        from founderos_atlas.web.mission import attention_from_health

        health = {"dimensions": [
            {"key": "policy-compliance", "state": "degraded",
             "summary": "2 evaluation(s) failed", "numerator": 3,
             "denominator": 5, "unit": "passed"},
            {"key": "active-incidents", "state": "critical",
             "summary": "1 interface down", "numerator": 1,
             "denominator": None, "unit": "active issues"},
            {"key": "configuration-drift", "state": "unavailable",
             "summary": "no comparison yet"},
            {"key": "reachability", "state": "healthy",
             "summary": "all good"},
        ]}
        items = attention_from_health(health)
        self.assertEqual(2, len(items))
        # Critical leads; each item carries severity, evidence, action.
        self.assertEqual("critical", items[0]["severity"])
        self.assertIn("Active incidents", items[0]["text"])
        self.assertEqual("/incidents?scope=all", items[0]["href"])
        self.assertEqual("warning", items[1]["severity"])
        self.assertIn("3/5 passed", items[1]["evidence"])
        self.assertEqual("/policy?scope=all", items[1]["href"])

    def test_unknown_and_unavailable_never_become_tasks(self) -> None:
        from founderos_atlas.web.mission import attention_from_health

        health = {"dimensions": [
            {"key": "configuration-drift", "state": "unavailable"},
            {"key": "active-incidents", "state": "unknown"},
        ]}
        self.assertEqual([], attention_from_health(health))

    def test_freshness_skip_rule(self) -> None:
        from founderos_atlas.web.mission import attention_from_health

        health = {"dimensions": [
            {"key": "discovery-freshness", "state": "stale",
             "summary": "older than 24h"},
        ]}
        self.assertEqual(1, len(attention_from_health(health)))
        self.assertEqual([], attention_from_health(
            health, skip=frozenset({"discovery-freshness"})
        ))


if __name__ == "__main__":
    unittest.main()
