"""Authenticated UI-preference persistence (audit-2, High #1).

The topology viewer persists layer choices through
``POST /api/preferences/ui``. In password/proxy modes that call MUST
carry the session cookie and the CSRF header — exactly what the fixed
viewer JavaScript now sends (same-origin credentials + ``X-Atlas-CSRF``
from the readable ``atlas_csrf`` cookie). These tests drive the same
wire protocol the browser uses, in every authentication mode, and prove
the server refuses the un-headered call it previously received.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in

LAYERS = {"unresolved": False, "ospf": True, "bgp": False}


class PasswordModeTests(unittest.TestCase):
    def test_the_viewer_wire_protocol_persists_layers(self) -> None:
        with production_world() as (app, _):
            admin, csrf = sign_in(app, "admin")
            # Exactly what the fixed viewer sends: JSON body + CSRF header
            # (cookies ride automatically, as with credentials:'same-origin').
            response = admin.post(
                "/api/preferences/ui",
                json={"key": "topology:layers", "value": LAYERS},
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.get_json()["saved"])
            read = admin.get(
                "/api/preferences/ui?key=topology:layers"
            ).get_json()
            self.assertEqual(LAYERS, read["value"])

    def test_the_old_unheadered_call_is_refused_not_silently_lost(self) -> None:
        with production_world() as (app, _):
            admin, _csrf = sign_in(app, "admin")
            response = admin.post(
                "/api/preferences/ui",
                json={"key": "topology:layers", "value": LAYERS},
            )
            # CSRF enforcement stands: the viewer must show this honestly,
            # never claim the preference was saved.
            self.assertEqual(403, response.status_code)

    def test_layers_are_isolated_between_users_and_survive_reauth(self) -> None:
        with production_world() as (app, _):
            admin, admin_csrf = sign_in(app, "admin")
            viewer, viewer_csrf = sign_in(app, "viewer")
            admin.post(
                "/api/preferences/ui",
                json={"key": "topology:layers", "value": {"ospf": False}},
                headers={"X-Atlas-CSRF": admin_csrf},
            )
            viewer.post(
                "/api/preferences/ui",
                json={"key": "topology:layers", "value": {"ospf": True}},
                headers={"X-Atlas-CSRF": viewer_csrf},
            )
            self.assertFalse(admin.get(
                "/api/preferences/ui?key=topology:layers"
            ).get_json()["value"]["ospf"])
            self.assertTrue(viewer.get(
                "/api/preferences/ui?key=topology:layers"
            ).get_json()["value"]["ospf"])
            # A fresh sign-in (browser restart) still reads the account's
            # own value — it lives server-side, never in the browser.
            fresh, _ = sign_in(app, "viewer")
            self.assertTrue(fresh.get(
                "/api/preferences/ui?key=topology:layers"
            ).get_json()["value"]["ospf"])


class ProxyModeTests(unittest.TestCase):
    def test_sso_users_persist_and_stay_isolated(self) -> None:
        from founderos_atlas.access import UserStore
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True)
            store = UserStore(workspace)
            store.create(username="sso-root", roles=("system-admin",))
            store.create(username="sso-vera", roles=("viewer",))
            with patch.dict("os.environ", {
                "ATLAS_PROXY_SECRET": "proxy-shared-secret-1",
            }):
                app = create_app(
                    output_dir=tmp, workspace_root=workspace,
                    auth_mode="proxy",
                )
            app.config.update(TESTING=True)
            client = app.test_client()

            def headers(user, csrf=None):
                base = {
                    "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
                    "X-Atlas-Remote-User": user,
                }
                if csrf:
                    base["X-Atlas-CSRF"] = csrf
                return base

            page = client.get("/", headers=headers("sso-root"))
            csrf = (
                page.get_data(as_text=True)
                .split('name="atlas-csrf" content="')[1].split('"')[0]
            )
            response = client.post(
                "/api/preferences/ui",
                json={"key": "topology:layers", "value": LAYERS},
                headers=headers("sso-root", csrf),
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual(LAYERS, client.get(
                "/api/preferences/ui?key=topology:layers",
                headers=headers("sso-root"),
            ).get_json()["value"])
            # vera never sees root's layers.
            self.assertIsNone(client.get(
                "/api/preferences/ui?key=topology:layers",
                headers=headers("sso-vera"),
            ).get_json()["value"])


class LocalModeTests(unittest.TestCase):
    def test_local_mode_keeps_working_and_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            response = client.post(
                "/api/preferences/ui",
                json={"key": "topology:layers", "value": LAYERS},
            )
            self.assertEqual(200, response.status_code)
            # Server restart: a fresh app over the same workspace.
            from founderos_atlas.web import create_app

            restarted = create_app(
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            restarted.config.update(TESTING=True)
            self.assertEqual(LAYERS, restarted.test_client().get(
                "/api/preferences/ui?key=topology:layers"
            ).get_json()["value"])


class ViewerContractTests(unittest.TestCase):
    def test_viewer_source_sends_csrf_and_reports_failure(self) -> None:
        """The generated viewer must carry the CSRF header on saves and
        own an honest, aria-live status element for refused saves."""

        source = Path(
            "src/founderos_atlas/visualization/templates/topology.html"
        ).read_text(encoding="utf-8")
        persist = source.split("function persist()")[1][:2500]
        self.assertIn("X-Atlas-CSRF", persist)
        self.assertIn("credentials: 'same-origin'", persist)
        self.assertIn("was not saved", persist)
        self.assertIn('id="layers-status"', source)
        self.assertIn('aria-live="polite"', source)
        # The old silent-swallow pattern is gone from the persist path.
        self.assertNotIn(".catch(function () {});", persist)


if __name__ == "__main__":
    unittest.main()
