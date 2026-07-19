"""Per-user hidden devices in the topology viewer.

"Remove from my view" is a display preference: persisted per user
through the UI-preference API, honest about itself in the summary line,
reversible in one click — and it never touches evidence, statistics,
exports, or another operator's view. Unresolved "?" peers, previously
right-click-dead, now offer exactly the action that makes sense for
them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world

VIEWER = Path("src/founderos_atlas/visualization/templates/topology.html")


class HiddenPreferenceTests(unittest.TestCase):
    def test_hidden_ids_round_trip_per_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            saved = client.post("/api/preferences/ui", json={
                "key": "topology:hidden",
                "value": {"ids": ["peer:unknown-a", "delhi-sw2"]},
            })
            self.assertEqual(200, saved.status_code)
            self.assertTrue(saved.get_json().get("saved"))
            read = client.get(
                "/api/preferences/ui?key=topology%3Ahidden"
            ).get_json()
            self.assertEqual(
                ["peer:unknown-a", "delhi-sw2"], read["value"]["ids"]
            )

    def test_two_operators_hide_independently(self) -> None:
        from tests.test_production_security import (
            production_world, sign_in,
        )

        with production_world() as (app, _workdir):
            operator, op_csrf = sign_in(app, "operator")
            viewer, v_csrf = sign_in(app, "viewer")
            operator.post(
                "/api/preferences/ui",
                json={"key": "topology:hidden", "value": {"ids": ["isp1"]}},
                headers={"X-Atlas-CSRF": op_csrf},
            )
            viewer.post(
                "/api/preferences/ui",
                json={"key": "topology:hidden", "value": {"ids": ["edge2"]}},
                headers={"X-Atlas-CSRF": v_csrf},
            )
            self.assertEqual(
                ["isp1"],
                operator.get("/api/preferences/ui?key=topology%3Ahidden")
                .get_json()["value"]["ids"],
            )
            self.assertEqual(
                ["edge2"],
                viewer.get("/api/preferences/ui?key=topology%3Ahidden")
                .get_json()["value"]["ids"],
            )


class ViewerContractTests(unittest.TestCase):
    """Source-level contract of the generated viewer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.viewer = VIEWER.read_text(encoding="utf-8")

    def test_hide_action_exists_and_is_scoped_to_the_user(self) -> None:
        self.assertIn("topology:hidden", self.viewer)
        self.assertIn("Hide from my view", self.viewer)
        # The action tells the truth about its scope.
        self.assertIn("YOUR view only", self.viewer)

    def test_unresolved_peers_get_a_menu(self) -> None:
        # Only sites stay menu-less; observed "?" peers offer the hide
        # action instead of silently ignoring the right-click.
        self.assertNotIn(
            "data.kind === 'observed' || data.kind === 'site'", self.viewer
        )
        self.assertIn("if (data.kind === 'site') { return; }", self.viewer)

    def test_summary_and_panel_stay_honest(self) -> None:
        self.assertIn("hidden by you", self.viewer)
        self.assertIn("Show them again", self.viewer)
        # A refused save is reported, never silently claimed.
        self.assertIn("Hidden-device choice was not saved", self.viewer)

    def test_layer_toggles_cannot_resurrect_hidden_nodes(self) -> None:
        # apply() repaints whole categories; the hidden set must win
        # again afterwards.
        self.assertIn("window.__atlasHiddenApply) { window.__atlasHiddenApply(); }",
                      self.viewer)

    def test_hidden_list_is_bounded(self) -> None:
        self.assertIn("MAX_HIDDEN = 200", self.viewer)


if __name__ == "__main__":
    unittest.main()
