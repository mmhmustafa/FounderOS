"""Content-Security-Policy compliance gates.

These tests FAIL the build on:

- any executable inline ``<script>`` in a template (JSON data blocks are
  the one approved, non-executable exception),
- any inline ``on*`` event handler,
- any ``javascript:`` URL,
- a normal page whose CSP would allow inline script,
- a destructive route that acts without server-verified confirmation,
- the loss of the data hooks the external modules depend on (wizard
  progression, scope switching, dirty-form guard, polling, console
  bootstrap, diagnostics copy, saved filters).

CSP must never be weakened to make these pass: the assertions go the
other way — they pin the strict policy down.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in

TEMPLATES = Path("src/founderos_atlas/web/templates")
STATIC = Path("src/founderos_atlas/web/static")

# <script ...> tags that are executable: no src= and not a data block.
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>")
_INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=\s*\"", re.I)
_JS_URL = re.compile(r"javascript:", re.I)

PRIMARY_ROUTES = (
    "/", "/incidents", "/advisor", "/paths", "/predict", "/compass",
    "/topology", "/policy", "/changes", "/timeline", "/history",
    "/configuration", "/evidence", "/discovery", "/discovery/wizard",
    "/discovery/console", "/profiles", "/profiles/new", "/credentials",
    "/audit", "/settings", "/inbox", "/users", "/management",
    "/system/integrity",
)


class TemplateSourceLintTests(unittest.TestCase):
    def test_no_executable_inline_scripts_in_any_template(self) -> None:
        offenders = []
        for template in sorted(TEMPLATES.glob("*.html")):
            for match in _INLINE_SCRIPT.finditer(
                template.read_text(encoding="utf-8")
            ):
                offenders.append(f"{template.name}: {match.group(0)[:70]}")
        self.assertEqual([], offenders)

    def test_no_inline_event_handlers_in_any_template(self) -> None:
        offenders = []
        for template in sorted(TEMPLATES.glob("*.html")):
            text = template.read_text(encoding="utf-8")
            for match in _INLINE_HANDLER.finditer(text):
                offenders.append(f"{template.name}: {match.group(0)!r}")
        self.assertEqual([], offenders)

    def test_no_javascript_urls_anywhere(self) -> None:
        offenders = []
        for path in list(TEMPLATES.glob("*.html")) + list(STATIC.glob("*.js")):
            if _JS_URL.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        self.assertEqual([], offenders)


class RenderedPageTests(unittest.TestCase):
    def test_rendered_pages_carry_no_inline_script_and_strict_csp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for route in PRIMARY_ROUTES:
                response = client.get(
                    route + "?scope=all", follow_redirects=True
                )
                body = response.data.decode("utf-8", errors="ignore")
                with self.subTest(route=route):
                    self.assertEqual(
                        [], _INLINE_SCRIPT.findall(body),
                        f"{route} renders an executable inline script",
                    )
                    self.assertEqual(
                        [], _INLINE_HANDLER.findall(body),
                        f"{route} renders an inline event handler",
                    )
                    csp = response.headers.get("Content-Security-Policy", "")
                    script_src = re.search(r"script-src ([^;]+)", csp)
                    self.assertIsNotNone(script_src, route)
                    self.assertNotIn("unsafe-inline", script_src.group(1))
                    self.assertIn("'self'", script_src.group(1))

    def test_every_script_reference_is_same_origin_static(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for route in PRIMARY_ROUTES:
                body = client.get(
                    route + "?scope=all", follow_redirects=True
                ).data.decode("utf-8", errors="ignore")
                for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', body):
                    with self.subTest(route=route, src=src):
                        self.assertTrue(
                            src.startswith("/static/"),
                            f"{route} loads a non-static script: {src}",
                        )
                        self.assertEqual(
                            200, client.get(src).status_code, src
                        )

    def test_artifact_exception_is_scoped_to_artifacts_only(self) -> None:
        """The relaxed policy exists solely for generated self-contained
        topology artifacts; nothing else may receive it."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            (workdir / "morning_brief.md").write_text("# brief", encoding="utf-8")
            artifact = client.get("/artifacts/morning_brief.md")
            self.assertIn(
                "unsafe-inline",
                artifact.headers.get("Content-Security-Policy", ""),
            )
            artifact.close()  # release the send_file handle (Windows tempdir)
            page = client.get("/?scope=all")
            self.assertNotIn(
                "script-src 'self' 'unsafe-inline'",
                page.headers.get("Content-Security-Policy", ""),
            )

    def test_only_topology_artifact_can_be_framed_same_origin(self) -> None:
        """The topology route embeds its generated viewer; every other
        application page and report artifact remains non-frameable."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            (workdir / "atlas_topology.html").write_text(
                "<html><body>viewer</body></html>", encoding="utf-8"
            )
            (workdir / "morning_brief.md").write_text(
                "# brief", encoding="utf-8"
            )

            viewer = client.get("/artifacts/atlas_topology.html")
            self.assertEqual("SAMEORIGIN", viewer.headers["X-Frame-Options"])
            self.assertIn(
                "frame-ancestors 'self'",
                viewer.headers["Content-Security-Policy"],
            )
            viewer.close()

            report = client.get("/artifacts/morning_brief.md")
            self.assertEqual("DENY", report.headers["X-Frame-Options"])
            self.assertIn(
                "frame-ancestors 'none'",
                report.headers["Content-Security-Policy"],
            )
            report.close()

            page = client.get("/?scope=all")
            self.assertEqual("DENY", page.headers["X-Frame-Options"])
            self.assertIn(
                "frame-ancestors 'none'",
                page.headers["Content-Security-Policy"],
            )


class BehaviorHookTests(unittest.TestCase):
    """The external modules and the data hooks they attach to."""

    def test_wizard_page_uses_external_module_with_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/discovery/wizard").data.decode("utf-8")
            self.assertIn("/static/atlas-wizard.js", page)
            self.assertIn("data-initial-step=", page)
            self.assertIn("data-next", page)
            self.assertIn("data-mode-fields", page)
            script = (STATIC / "atlas-wizard.js").read_text(encoding="utf-8")
            for hook in ("data-draft-jump", "reportValidity",
                         "/api/discovery/wizard/drafts", "updateModes"):
                self.assertIn(hook, script)

    def test_scope_switcher_autosubmits_with_noscript_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertIn('name="scope" data-autosubmit', page)
            self.assertIn("<noscript><button", page)
            script = (STATIC / "atlas.js").read_text(encoding="utf-8")
            self.assertIn("data-autosubmit", script)

    def test_profile_dirty_guard_and_console_hooks_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            form = client.get("/profiles/new").data.decode("utf-8")
            self.assertIn("data-dirty-guard", form)
            settings = client.get("/settings").data.decode("utf-8")
            self.assertIn("data-copy-url", settings)
            evidence = client.get("/evidence?scope=all").data.decode("utf-8")
            self.assertIn("data-save-evidence-filter", evidence)
            ops = client.get("/discovery/console").data.decode("utf-8")
            self.assertIn("/static/atlas-discovery-console.js", ops)
            shared = (STATIC / "atlas.js").read_text(encoding="utf-8")
            for hook in ("data-dirty-guard", "data-copy-url",
                         "data-save-evidence-filter", "atlas-console-config",
                         "AtlasConsole"):
                self.assertIn(hook, shared)
            polling = (STATIC / "atlas-discovery-console.js").read_text(
                encoding="utf-8"
            )
            self.assertIn("/api/discovery/execution/demo", polling)

    def test_console_template_uses_json_config_not_executable_script(self) -> None:
        text = (TEMPLATES / "console.html").read_text(encoding="utf-8")
        self.assertIn('type="application/json" id="atlas-console-config"', text)
        self.assertNotIn("window.ATLAS_CONSOLE", text)


class DestructiveConfirmationTests(unittest.TestCase):
    @staticmethod
    def _token(body: str) -> str:
        match = re.search(r'name="_confirm_token" value="([^"]+)"', body)
        assert match, "confirmation page carries no token"
        return match.group(1)

    def test_profile_deletion_requires_server_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)
            first = client.post("/profiles/Hyderabad/delete", data={})
            self.assertEqual(200, first.status_code)
            body = first.data.decode("utf-8")
            self.assertIn("Delete profile Hyderabad", body)
            # Nothing was deleted by the unconfirmed request.
            self.assertTrue(service.repository.exists("Hyderabad"))
            token = self._token(body)
            confirmed = client.post(
                "/profiles/Hyderabad/delete",
                data={"_confirm_token": token},
                follow_redirects=True,
            )
            self.assertEqual(200, confirmed.status_code)
            self.assertFalse(service.repository.exists("Hyderabad"))

    def test_confirmation_token_is_bound_to_its_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)
            body = client.post(
                "/profiles/Hyderabad/delete", data={}
            ).data.decode("utf-8")
            token = self._token(body)
            # The same token must not authorize a DIFFERENT deletion.
            other = client.post(
                "/profiles/Secunderabad/delete",
                data={"_confirm_token": token},
            )
            self.assertEqual(200, other.status_code)
            self.assertTrue(service.repository.exists("Secunderabad"))
            self.assertIn(b"Delete profile Secunderabad", other.data)

    def test_wizard_draft_cancellation_requires_confirmation(self) -> None:
        from founderos_atlas.workspace.administration import (
            AdministrationRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            repo = AdministrationRepository(workdir / "workspace")
            draft_id = repo.save_draft(None, {"name": "Lab sweep"})
            first = client.post(
                f"/discovery/wizard/drafts/{draft_id}/cancel", data={}
            )
            self.assertEqual(200, first.status_code)
            self.assertIsNotNone(repo.get_draft(draft_id))
            client.post(
                f"/discovery/wizard/drafts/{draft_id}/cancel",
                data={"_confirm_token": self._token(first.data.decode())},
            )
            self.assertIsNone(repo.get_draft(draft_id))

    def test_advisor_conversation_deletion_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            client.post("/advisor/ask", data={"question": "What changed?"})
            from founderos_atlas.advisor import ConversationRepository

            conversations = ConversationRepository(workdir)
            self.assertEqual(1, len(conversations.list_conversations()))
            first = client.post("/advisor/conversations/0/delete", data={})
            self.assertEqual(200, first.status_code)
            self.assertEqual(1, len(conversations.list_conversations()))
            client.post(
                "/advisor/conversations/0/delete",
                data={"_confirm_token": self._token(first.data.decode())},
            )
            self.assertEqual(0, len(conversations.list_conversations()))

    def test_credential_deletion_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            added = client.post("/credentials", data={
                "set_name": "Lab", "label": "Admin",
                "username": "atlas", "password": "secret-pw-123456",
            }, follow_redirects=True)
            self.assertEqual(200, added.status_code)
            first = client.post("/credentials/lab/admin/delete", data={})
            self.assertEqual(200, first.status_code)
            self.assertIn(b"Delete credential admin", first.data)
            client.post(
                "/credentials/lab/admin/delete",
                data={"_confirm_token": self._token(first.data.decode())},
                follow_redirects=True,
            )
            page = client.get("/credentials").data.decode("utf-8")
            self.assertNotIn(">Admin<", page)

    def test_user_deletion_requires_confirmation_in_production(self) -> None:
        from tests.test_production_security import PASSWORDS

        with production_world() as (app, _):
            admin, csrf = sign_in(app, "admin")
            first = admin.post("/users/viewer/delete", data={
                "_csrf": csrf, "admin_password": PASSWORDS["admin"],
            })
            self.assertEqual(200, first.status_code)
            store = app.config["ATLAS_USER_STORE"]
            self.assertIsNotNone(store.get("viewer"))
            body = first.data.decode()
            # The confirmation page never echoes the password.
            self.assertNotIn(PASSWORDS["admin"], body)
            admin.post("/users/viewer/delete", data={
                "_csrf": csrf,
                "_confirm_token": self._token(body),
                "expected_revision": str(store.revision()),
            })
            self.assertIsNone(store.get("viewer"))


if __name__ == "__main__":
    unittest.main()
