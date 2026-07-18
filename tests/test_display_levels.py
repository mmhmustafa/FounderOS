"""Progressive-disclosure display levels (PR: calmer UX foundation).

Simple / Detailed / Expert as a persistent, per-user preference: server
stored (never localStorage-only), isolated per user in password and
proxy modes, surviving browser and server restarts, defaulting new
workspaces to Simple and pre-existing workspaces to Expert, and never
changing what RBAC allows — only how much detail pages open with.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from founderos_atlas.workspace.user_preferences import (
    DISPLAY_LEVELS,
    UserPreferenceStore,
)

from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in


class StoreTests(unittest.TestCase):
    def test_fresh_workspace_defaults_to_simple(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserPreferenceStore(tmp)
            self.assertEqual("simple", store.display_level("anyone"))

    def test_a_set_level_persists_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            UserPreferenceStore(tmp).set_display_level("alice", "expert")
            # A fresh store over the same path is a server restart.
            self.assertEqual(
                "expert", UserPreferenceStore(tmp).display_level("alice")
            )

    def test_levels_are_isolated_per_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserPreferenceStore(tmp)
            store.set_display_level("alice", "expert")
            store.set_display_level("bob", "detailed")
            self.assertEqual("expert", store.display_level("alice"))
            self.assertEqual("detailed", store.display_level("bob"))
            self.assertEqual("simple", store.display_level("carol"))

    def test_invalid_level_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                UserPreferenceStore(tmp).set_display_level("alice", "wizard")

    def test_corrupt_store_falls_back_without_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserPreferenceStore(tmp)
            store.set_display_level("alice", "expert")
            store.path.write_text("{not json", encoding="utf-8")
            self.assertEqual("simple", store.display_level("alice"))
            # And the store recovers on the next write.
            store.set_display_level("alice", "detailed")
            self.assertEqual("detailed", store.display_level("alice"))

    def test_corrupt_value_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserPreferenceStore(tmp)
            store.set_display_level("alice", "expert")
            raw = store.path.read_text(encoding="utf-8")
            store.path.write_text(
                raw.replace('"expert"', '"turbo"'), encoding="utf-8"
            )
            self.assertEqual("simple", store.display_level("alice"))

    def test_existing_workspace_marker_defaults_to_expert(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Prior activity: this workspace predates the feature.
            (root / "profiles.json").write_text("{}", encoding="utf-8")
            migrate_workspace(root)
            store = UserPreferenceStore(root)
            self.assertEqual("expert", store.display_level("anyone"))
            # An explicit personal choice still wins.
            store.set_display_level("anyone", "simple")
            self.assertEqual("simple", store.display_level("anyone"))

    def test_brand_new_workspace_gets_no_expert_marker(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            migrate_workspace(tmp)
            self.assertEqual(
                "simple", UserPreferenceStore(tmp).display_level("anyone")
            )


class LocalModeTests(unittest.TestCase):
    def test_shell_and_settings_expose_the_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/settings").get_data(as_text=True)
            self.assertIn('data-display-level="', page)
            self.assertIn('action="/preferences/display-level"', page)
            self.assertIn("Save display level", page)
            for level in DISPLAY_LEVELS:
                self.assertIn(f'value="{level}"', page)

    def test_change_persists_across_server_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            response = client.post("/preferences/display-level", data={
                "display_level": "expert", "next": "/settings",
            }, follow_redirects=True)
            self.assertIn(
                "Display level set to expert",
                response.get_data(as_text=True),
            )
            self.assertIn(
                'data-display-level="expert"',
                client.get("/").get_data(as_text=True),
            )
            # A brand-new app over the same workspace is a server restart;
            # a brand-new client is a browser restart (no cookies carry
            # the preference — it lives server-side).
            from founderos_atlas.web import create_app

            restarted_app = create_app(
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            restarted_app.config.update(TESTING=True)
            restarted = restarted_app.test_client()
            self.assertIn(
                'data-display-level="expert"',
                restarted.get("/").get_data(as_text=True),
            )

    def test_invalid_level_flashes_and_keeps_the_old_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            client.post("/preferences/display-level", data={
                "display_level": "detailed",
            })
            response = client.post("/preferences/display-level", data={
                "display_level": "turbo",
            }, follow_redirects=True)
            self.assertIn(
                "Display level must be one of",
                response.get_data(as_text=True),
            )
            self.assertIn(
                'data-display-level="detailed"',
                client.get("/").get_data(as_text=True),
            )

    def test_density_and_level_are_separate_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            client.post("/preferences/display-level", data={
                "display_level": "expert",
            })
            page = client.get("/").get_data(as_text=True)
            self.assertIn('data-display-level="expert"', page)
            self.assertIn('data-density="comfortable"', page)
            # Changing density (workspace preference) leaves the level alone.
            client.post("/settings", data={
                "timezone": "auto", "theme": "dark", "density": "compact",
                "retention_days": "365", "log_level": "INFO",
            })
            page = client.get("/").get_data(as_text=True)
            self.assertIn('data-density="compact"', page)
            self.assertIn('data-theme="dark"', page)
            self.assertIn('data-display-level="expert"', page)


class PasswordModeTests(unittest.TestCase):
    def test_levels_are_per_account_and_survive_reauth(self) -> None:
        with production_world() as (app, _workdir):
            admin, admin_csrf = sign_in(app, "admin")
            viewer, viewer_csrf = sign_in(app, "viewer")
            admin.post("/preferences/display-level", data={
                "_csrf": admin_csrf, "display_level": "expert",
            })
            viewer.post("/preferences/display-level", data={
                "_csrf": viewer_csrf, "display_level": "detailed",
            })
            self.assertIn(
                'data-display-level="expert"',
                admin.get("/").get_data(as_text=True),
            )
            self.assertIn(
                'data-display-level="detailed"',
                viewer.get("/").get_data(as_text=True),
            )
            # A fresh sign-in (new browser) still sees the account's level.
            fresh, _ = sign_in(app, "viewer")
            self.assertIn(
                'data-display-level="detailed"',
                fresh.get("/").get_data(as_text=True),
            )

    def test_rbac_is_identical_in_every_display_mode(self) -> None:
        with production_world() as (app, _workdir):
            viewer, csrf = sign_in(app, "viewer")
            for level in DISPLAY_LEVELS:
                viewer.post("/preferences/display-level", data={
                    "_csrf": csrf, "display_level": level,
                })
                # A viewer can read pages at every level...
                self.assertEqual(200, viewer.get("/settings").status_code)
                # ...and is denied admin routes at every level.
                self.assertEqual(
                    403, viewer.get("/settings/retention").status_code
                )
                self.assertEqual(403, viewer.post(
                    "/settings", data={"_csrf": csrf, "timezone": "auto"},
                ).status_code)


class ProxyModeTests(unittest.TestCase):
    def test_sso_users_have_isolated_levels(self) -> None:
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

            def headers(user):
                return {
                    "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
                    "X-Atlas-Remote-User": user,
                }

            page = client.get("/settings", headers=headers("sso-root"))
            csrf = (
                page.get_data(as_text=True)
                .split('name="atlas-csrf" content="')[1].split('"')[0]
            )
            client.post(
                "/preferences/display-level",
                data={"_csrf": csrf, "display_level": "detailed"},
                headers=headers("sso-root"),
            )
            self.assertIn(
                'data-display-level="detailed"',
                client.get("/", headers=headers("sso-root"))
                .get_data(as_text=True),
            )
            # Users existed before the first migration ran, so this
            # workspace carries the pre-disclosure marker: vera keeps the
            # honest EXPERT default, untouched by root's choice.
            self.assertIn(
                'data-display-level="expert"',
                client.get("/", headers=headers("sso-vera"))
                .get_data(as_text=True),
            )


class DisclosureMacroTests(unittest.TestCase):
    TEMPLATE = """
    {% import "_disclosure.html" as d with context %}
    {{ d.page_summary("Network healthy.", tone="good") }}
    {% call d.advanced_details("Protocol internals") %}deep facts{% endcall %}
    {% call d.secondary_actions() %}<a href="/x">Export</a>{% endcall %}
    {{ d.warning_disclosure("3 interfaces are down.") }}
    {{ d.technical_metadata([("snapshot", "abc123")]) }}
    {{ d.empty_state("No incidents.", "Nothing needs attention.") }}
    """

    def _render(self, level: str) -> str:
        from flask import render_template_string

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            with client.application.test_request_context("/"):
                return render_template_string(
                    self.TEMPLATE, display_level=level,
                )

    def test_expert_opens_advanced_and_technical_sections(self) -> None:
        html = self._render("expert")
        self.assertIn('class="disclosure disclosure-advanced" open', html)
        self.assertIn('class="disclosure disclosure-technical" open', html)

    def test_simple_keeps_sections_present_but_collapsed(self) -> None:
        html = self._render("simple")
        self.assertIn("disclosure-advanced", html)
        self.assertNotIn('disclosure-advanced" open', html)
        # The content is still IN the page — collapsed, never removed.
        self.assertIn("deep facts", html)
        self.assertIn("Export", html)

    def test_warnings_are_visible_at_every_level(self) -> None:
        for level in DISPLAY_LEVELS:
            html = self._render(level)
            self.assertIn("3 interfaces are down.", html)
            self.assertIn('role="status"', html)

    def test_summaries_are_keyboard_reachable_semantic_html(self) -> None:
        html = self._render("simple")
        # Native details/summary: keyboard-operable without any JS.
        self.assertIn("<details", html)
        self.assertIn("<summary>", html)


def build_world_app(workdir):  # kept for symmetry with other suites
    return build_world(workdir)


if __name__ == "__main__":
    unittest.main()
