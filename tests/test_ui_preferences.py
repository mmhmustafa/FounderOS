"""Generic per-user UI preferences + topology Layers control.

The UI-preference API stores personal presentation state (topology
layers, table columns, workflow advanced-open) per user, namespace-
allowlisted and size-capped, isolated per account, surviving restarts.
The topology viewer's Layers control persists through it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from founderos_atlas.workspace.user_preferences import UserPreferenceStore

from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in


class StoreTests(unittest.TestCase):
    def test_namespaced_value_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserPreferenceStore(tmp)
            store.set_ui_value("alice", "topology:layers", {"ospf": False})
            self.assertEqual(
                {"ospf": False},
                store.ui_value("alice", "topology:layers"),
            )
            self.assertIsNone(store.ui_value("bob", "topology:layers"))

    def test_disallowed_namespace_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                UserPreferenceStore(tmp).set_ui_value("alice", "secret:key", 1)

    def test_oversized_value_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                UserPreferenceStore(tmp).set_ui_value(
                    "alice", "table:cols", {"x": "y" * 5000}
                )

    def test_display_level_and_ui_values_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserPreferenceStore(tmp)
            store.set_display_level("alice", "expert")
            store.set_ui_value("alice", "topology:layers", {"bgp": True})
            self.assertEqual("expert", store.display_level("alice"))
            self.assertEqual(
                {"bgp": True}, store.ui_value("alice", "topology:layers")
            )


class ApiTests(unittest.TestCase):
    def test_set_and_get_round_trip_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            response = client.post("/api/preferences/ui", json={
                "key": "topology:layers", "value": {"unresolved": True},
            })
            self.assertEqual(200, response.status_code)
            got = client.get(
                "/api/preferences/ui?key=topology:layers"
            ).get_json()
            self.assertEqual({"unresolved": True}, got["value"])
            # Server restart: a new app over the same workspace still reads it.
            from founderos_atlas.web import create_app

            app = create_app(
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            restarted = app.test_client()
            self.assertEqual(
                {"unresolved": True},
                restarted.get(
                    "/api/preferences/ui?key=topology:layers"
                ).get_json()["value"],
            )

    def test_bad_namespace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            self.assertEqual(400, client.post("/api/preferences/ui", json={
                "key": "evil:x", "value": 1,
            }).status_code)
            self.assertEqual(400, client.get(
                "/api/preferences/ui?key=evil:x"
            ).status_code)

    def test_values_are_isolated_per_account(self) -> None:
        with production_world() as (app, _):
            admin, acsrf = sign_in(app, "admin")
            viewer, vcsrf = sign_in(app, "viewer")
            admin.post("/api/preferences/ui", json={
                "key": "topology:layers", "value": {"ospf": False},
            }, headers={"X-Atlas-CSRF": acsrf})
            viewer.post("/api/preferences/ui", json={
                "key": "topology:layers", "value": {"ospf": True},
            }, headers={"X-Atlas-CSRF": vcsrf})
            self.assertEqual(
                {"ospf": False},
                admin.get(
                    "/api/preferences/ui?key=topology:layers"
                ).get_json()["value"],
            )
            self.assertEqual(
                {"ospf": True},
                viewer.get(
                    "/api/preferences/ui?key=topology:layers"
                ).get_json()["value"],
            )


class ViewerLayersTests(unittest.TestCase):
    def test_layers_control_is_in_the_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            # The enterprise viewer artifact carries the Layers control.
            art = client.get(
                "/artifacts/.atlas/enterprise/atlas_topology.html"
            )
            if art.status_code != 200:
                self.skipTest("no enterprise artifact in this fixture")
            html = art.get_data(as_text=True)
            for layer in ("sites", "verified", "observed", "devices",
                          "ospf", "bgp", "unresolved", "interfaceLabels",
                          "evidenceLabels"):
                self.assertIn(f'data-layer="{layer}"', html)
            self.assertIn("Reset to recommended", html)
            self.assertIn("/api/preferences/ui", html)


class GuidedWorkflowTests(unittest.TestCase):
    def test_profile_advanced_section_is_remembered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/profiles/new").get_data(as_text=True)
            # The advanced section opts into per-user remembered state.
            self.assertIn('data-remember="workflow:profile-advanced"', page)
            # And the JS enhancements ship (auto-reveal + remember).
            js = Path(
                "src/founderos_atlas/web/static/atlas.js"
            ).read_text(encoding="utf-8")
            self.assertIn('addEventListener("invalid"', js)
            self.assertIn('data-remember', js)

    def test_workflow_namespace_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            ok = client.post("/api/preferences/ui", json={
                "key": "workflow:profile-advanced", "value": True,
            })
            self.assertEqual(200, ok.status_code)
            self.assertTrue(client.get(
                "/api/preferences/ui?key=workflow:profile-advanced"
            ).get_json()["value"])


class SettingsSeparationTests(unittest.TestCase):
    def test_settings_groups_personal_from_administration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/settings").get_data(as_text=True)
            self.assertIn("Personal preferences", page)
            self.assertIn("Data, backup", page)
            # Personal group precedes the admin group.
            self.assertLess(
                page.index("Personal preferences"),
                page.index("Data, backup"),
            )


if __name__ == "__main__":
    unittest.main()
