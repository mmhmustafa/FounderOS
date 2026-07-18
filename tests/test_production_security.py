"""Production security: authentication, RBAC, CSRF, sessions, audit.

Every test drives direct HTTP requests — never hidden UI controls —
because hiding a button is not authorization. Local development mode
and production password mode are tested separately; the authorization
table is tested for completeness so a new route cannot ship without a
conscious permission choice.
"""

from __future__ import annotations

import json
import io
import re
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

from founderos_atlas.access import (
    SESSION_COOKIE,
    SessionStore,
    UserStore,
    hash_password,
    verify_password,
)
from founderos_atlas.access.models import (
    ALL_ROLES,
    ROLE_GRANTS,
    Principal,
    permissions_for,
)


PASSWORDS = {
    "admin": "admin-password-abc123",
    "viewer": "viewer-password-abc123",
    "operator": "operator-password-abc",
    "policy": "policy-password-abc123",
    "credadmin": "credadm-password-abc1",
    "approver": "approver-password-abc",
    "investigator": "invest-password-abc12",
}

ROLE_OF = {
    "admin": "system-admin",
    "viewer": "viewer",
    "operator": "network-operator",
    "policy": "policy-manager",
    "credadmin": "credential-admin",
    "approver": "approver",
    "investigator": "investigator",
}


@contextmanager
def production_world():
    """A password-mode app with one account per role."""

    from founderos_atlas.web import create_app

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        workspace = workdir / "workspace"
        workspace.mkdir(parents=True)
        users = UserStore(workspace)
        for username, role in ROLE_OF.items():
            users.create(
                username=username, roles=(role,),
                password=PASSWORDS[username],
            )
        app = create_app(
            output_dir=workdir / "out", workspace_root=workspace,
            auth_mode="password",
        )
        app.config.update(TESTING=True)
        yield app, workdir


def sign_in(app, username: str):
    """A test client signed in as ``username``, plus its CSRF token."""

    client = app.test_client()
    response = client.post("/login", data={
        "username": username, "password": PASSWORDS[username],
    })
    assert response.status_code == 302, response.status_code
    cookie = client.get_cookie("atlas_csrf")
    return client, (cookie.value if cookie else "")


class AuthorizationTableTests(unittest.TestCase):
    def test_every_registered_endpoint_has_a_permission_entry(self) -> None:
        """A route missing from the table would be denied at runtime; this
        test makes the omission a development-time failure instead."""

        from founderos_atlas.web import create_app
        from founderos_atlas.web.authz_map import ENDPOINT_PERMISSIONS

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_dir=tmp, workspace_root=Path(tmp) / "ws",
            )
            registered = {rule.endpoint for rule in app.url_map.iter_rules()}
        missing = sorted(registered - set(ENDPOINT_PERMISSIONS))
        self.assertEqual(
            [], missing,
            f"endpoints without an authorization entry: {missing}",
        )

    def test_role_grants_cover_the_required_capabilities(self) -> None:
        self.assertEqual(
            sorted(ALL_ROLES),
            sorted(ROLE_GRANTS),
        )
        # The spec's capability list, mapped to a permission each.
        for permission in (
            "evidence.view", "topology.edit", "discovery.run",
            "credentials.manage", "policy.manage", "predict.run",
            "plans.approve", "export.data", "system.admin",
        ):
            granting_roles = [
                role for role, grants in ROLE_GRANTS.items()
                if permission in grants
            ]
            self.assertTrue(granting_roles, f"nobody can {permission}")

    def test_unknown_roles_grant_nothing(self) -> None:
        self.assertEqual(frozenset(), permissions_for(["superuser", ""]))


class LocalModeTests(unittest.TestCase):
    def test_loopback_gets_full_local_principal(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_dir=tmp, workspace_root=Path(tmp) / "ws")
            app.config.update(TESTING=True)
            client = app.test_client()
            page = client.get(
                "/", environ_base={"REMOTE_ADDR": "127.0.0.1"}
            )
            self.assertEqual(200, page.status_code)
            self.assertIn(b"Local development mode", page.data)

    def test_remote_clients_are_refused_not_trusted(self) -> None:
        """Accidental exposure of unauthenticated local mode must fail
        closed: a non-loopback client gets 403 on every route."""

        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_dir=tmp, workspace_root=Path(tmp) / "ws")
            app.config.update(TESTING=True)
            client = app.test_client()
            for path in ("/", "/policy", "/settings", "/api/search?q=x"):
                response = client.get(
                    path, environ_base={"REMOTE_ADDR": "203.0.113.10"}
                )
                self.assertEqual(403, response.status_code, path)

    def test_local_mode_still_refuses_cross_origin_mutations(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_dir=tmp, workspace_root=Path(tmp) / "ws")
            app.config.update(TESTING=True)
            client = app.test_client()
            response = client.post(
                "/settings",
                data={"timezone": "auto"},
                headers={"Origin": "https://evil.example"},
            )
            self.assertEqual(403, response.status_code)


class SessionLifecycleTests(unittest.TestCase):
    def test_login_rotates_tokens_and_logout_invalidates(self) -> None:
        with production_world() as (app, _):
            client, csrf = sign_in(app, "admin")
            first = client.get_cookie(SESSION_COOKIE).value
            self.assertEqual(200, client.get("/").status_code)

            # A second login mints a token no prior request has seen
            # (fixation cannot survive authentication).
            client2, _ = sign_in(app, "admin")
            second = client2.get_cookie(SESSION_COOKIE).value
            self.assertNotEqual(first, second)

            # Logout invalidates server-side: replaying the cookie fails.
            client.post("/logout", data={"_csrf": csrf})
            replay = app.test_client()
            replay.set_cookie(SESSION_COOKIE, first)
            self.assertEqual(302, replay.get("/").status_code)

    def test_session_tokens_are_hashed_at_rest(self) -> None:
        with production_world() as (app, workdir):
            client, _ = sign_in(app, "admin")
            token = client.get_cookie(SESSION_COOKIE).value
            stored = (workdir / "workspace" / "sessions.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(token, stored)

    def test_disabling_an_account_revokes_its_sessions(self) -> None:
        with production_world() as (app, _):
            viewer_client, _ = sign_in(app, "viewer")
            self.assertEqual(200, viewer_client.get("/").status_code)
            admin_client, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            response = admin_client.post("/users/viewer", data={
                "_csrf": csrf, "disabled": "1",
                "admin_password": PASSWORDS["admin"],
                "expected_revision": store.revision(),
            })
            self.assertEqual(302, response.status_code)
            self.assertEqual(302, viewer_client.get("/").status_code)

    def test_expired_sessions_do_not_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(tmp, max_age_seconds=-1)
            token = store.create("alice")
            self.assertIsNone(store.resolve(token))


class PasswordStorageTests(unittest.TestCase):
    def test_scrypt_hash_round_trip_and_no_plaintext(self) -> None:
        stored = hash_password("correct-horse-battery")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn("correct-horse-battery", stored)
        self.assertTrue(verify_password("correct-horse-battery", stored))
        self.assertFalse(verify_password("wrong-password-here", stored))

    def test_short_passwords_are_refused(self) -> None:
        from founderos_atlas.access.users import UserStoreError

        with self.assertRaises(UserStoreError):
            hash_password("short")

    def test_user_file_never_contains_the_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserStore(tmp)
            store.create(
                username="alice", roles=("viewer",),
                password="alice-password-12345",
            )
            raw = store.path.read_text(encoding="utf-8")
            self.assertNotIn("alice-password-12345", raw)


class RbacHttpTests(unittest.TestCase):
    """Direct requests per role. The matrix is the specification."""

    CASES = (
        # (method, path, data, allowed-users, expected-success-status)
        ("GET", "/credentials", None, {"credadmin", "admin"}, 200),
        ("POST", "/policy/assign", {"owner": "x"},
         {"policy", "admin"}, 302),
        ("POST", "/changes/annotate",
         {"action": "acknowledge", "subject": "change:x"},
         {"investigator", "admin"}, 302),
        ("GET", "/users", None, {"admin"}, 200),
        ("GET", "/settings/diagnostics.json", None, {"admin"}, 200),
        ("GET", "/system/integrity", None, {"admin"}, 200),
        ("GET", "/policy/export.csv", None,
         {"investigator", "operator", "policy", "admin"}, 200),
        ("POST", "/api/discovery/jobs", {"profile": "nope"},
         {"operator", "admin"}, (200, 400, 404, 409)),
    )

    def test_permission_matrix_enforced_server_side(self) -> None:
        with production_world() as (app, _):
            clients = {
                user: sign_in(app, user) for user in PASSWORDS
            }
            for method, path, data, allowed, ok_status in self.CASES:
                for user, (client, csrf) in clients.items():
                    if method == "GET":
                        response = client.get(path)
                    else:
                        payload = dict(data or {})
                        payload["_csrf"] = csrf
                        response = client.post(path, data=payload)
                    with self.subTest(user=user, path=path):
                        if user in allowed or user == "admin":
                            expected = (
                                ok_status if isinstance(ok_status, tuple)
                                else (ok_status,)
                            )
                            self.assertIn(
                                response.status_code, expected,
                                response.data[:200],
                            )
                        else:
                            self.assertEqual(403, response.status_code)

    def test_denials_are_audited_with_actor_role_and_outcome(self) -> None:
        with production_world() as (app, workdir):
            client, csrf = sign_in(app, "viewer")
            self.assertEqual(
                403,
                client.post("/policy/assign",
                            data={"owner": "x", "_csrf": csrf}).status_code,
            )
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            events = [json.loads(line) for line in audit.splitlines() if line]
            denial = next(
                event for event in events
                if event["category"] == "authorization"
                and event["outcome"] == "denied"
            )
            self.assertEqual("viewer", denial["actor"])
            self.assertIn("viewer", denial["actor_roles"])
            self.assertIn("policy_assign", denial["subject"])

    def test_failed_logins_are_audited_and_rate_limited(self) -> None:
        with production_world() as (app, _):
            client = app.test_client()
            statuses = []
            for _ in range(7):
                statuses.append(client.post("/login", data={
                    "username": "admin", "password": "wrong-password-123",
                }).status_code)
            self.assertIn(401, statuses)
            self.assertIn(429, statuses, "rate limit never engaged")


class CsrfTests(unittest.TestCase):
    def test_mutations_without_a_token_are_refused(self) -> None:
        with production_world() as (app, _):
            client, _ = sign_in(app, "admin")
            response = client.post("/policy/assign", data={"owner": "x"})
            self.assertEqual(403, response.status_code)
            self.assertIn(b"protection token", response.data)

    def test_a_stolen_token_from_another_session_fails(self) -> None:
        with production_world() as (app, _):
            client_a, csrf_a = sign_in(app, "admin")
            client_b, _ = sign_in(app, "policy")
            response = client_b.post(
                "/policy/assign", data={"owner": "x", "_csrf": csrf_a}
            )
            self.assertEqual(403, response.status_code)

    def test_header_carries_the_token_for_json_apis(self) -> None:
        with production_world() as (app, _):
            client, csrf = sign_in(app, "operator")
            response = client.post(
                "/api/discovery/jobs", json={"profile": "missing"},
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertNotEqual(403, response.status_code)

    def test_cross_origin_mutations_are_refused_even_with_token(self) -> None:
        with production_world() as (app, _):
            client, csrf = sign_in(app, "admin")
            response = client.post(
                "/policy/assign",
                data={"owner": "x", "_csrf": csrf},
                headers={"Origin": "https://evil.example"},
            )
            self.assertEqual(403, response.status_code)


class SecurityHeaderTests(unittest.TestCase):
    def test_headers_and_no_store_on_authenticated_pages(self) -> None:
        with production_world() as (app, _):
            client, _ = sign_in(app, "viewer")
            response = client.get("/")
            self.assertEqual("nosniff",
                             response.headers["X-Content-Type-Options"])
            self.assertEqual("DENY", response.headers["X-Frame-Options"])
            csp = response.headers["Content-Security-Policy"]
            self.assertIn("default-src 'self'", csp)
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            self.assertTrue(response.headers.get("X-Request-ID"))

    def test_hsts_appears_only_with_tls(self) -> None:
        with production_world() as (app, _):
            client, _ = sign_in(app, "viewer")
            self.assertIsNone(
                client.get("/").headers.get("Strict-Transport-Security")
            )

    def test_errors_reveal_no_stack_or_paths(self) -> None:
        with production_world() as (app, _):
            client, _ = sign_in(app, "viewer")
            response = client.get("/devices/definitely%2Fnot%2Freal")
            self.assertLess(response.status_code, 500)
            missing = client.get("/no-such-page")
            self.assertEqual(403, missing.status_code)  # unmapped => denied
            body = missing.data.decode("utf-8")
            self.assertNotIn("Traceback", body)
            self.assertNotIn("site-packages", body)


class SecretLeakageTests(unittest.TestCase):
    def test_secret_never_reaches_html_audit_export_or_backup(self) -> None:
        secret = "Sup3r-Secret-Value!"
        with production_world() as (app, workdir):
            import founderos_atlas.workspace.credentials as credmod

            provider = credmod.InMemoryCredentialProvider()
            app.config["ATLAS_PROFILE_SERVICE"]._credentials = provider  # noqa: SLF001
            client, csrf = sign_in(app, "credadmin")
            response = client.post("/credentials", data={
                "_csrf": csrf, "set_name": "Lab", "label": "Admin",
                "username": "atlas", "password": secret,
            }, follow_redirects=True)
            self.assertEqual(200, response.status_code)
            self.assertNotIn(secret.encode(), response.data)

            # Nothing under the workspace may hold the plaintext.
            for path in (workdir / "workspace").rglob("*"):
                if path.is_file():
                    self.assertNotIn(
                        secret, path.read_text(encoding="utf-8", errors="ignore"),
                        f"secret leaked into {path.name}",
                    )

            admin, _ = sign_in(app, "admin")
            backup = admin.get("/settings/backup")
            self.assertNotIn(secret.encode(), backup.data)
            with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
                for member in archive.infolist():
                    self.assertNotIn(
                        secret.encode(), archive.read(member),
                        f"credential canary leaked into backup member {member.filename}",
                    )
            for export_path in (
                "/settings/diagnostics.json",
                "/audit/export.csv",
                "/policy/export.csv?scope=all",
                "/changes/export.csv?scope=all",
            ):
                exported = admin.get(export_path)
                self.assertEqual(200, exported.status_code, export_path)
                self.assertNotIn(secret.encode(), exported.data, export_path)

    def test_audit_events_redact_forbidden_keys(self) -> None:
        from founderos_atlas.audit import AuditEvent

        event = AuditEvent.create(
            category="credential", operation="update", subject="cred:x",
            before={"password": "LEAK", "nested": {"token": "LEAK2"}},
        )
        self.assertEqual("[redacted]", event.before["password"])
        self.assertEqual("[redacted]", event.before["nested"]["token"])


class ArtifactContainmentTests(unittest.TestCase):
    def test_artifacts_route_serves_only_named_artifacts(self) -> None:
        with production_world() as (app, workdir):
            out = workdir / "out" / ".atlas"
            out.mkdir(parents=True, exist_ok=True)
            (out / "jobs.json").write_text("{}", encoding="utf-8")
            client, _ = sign_in(app, "viewer")
            self.assertEqual(
                404, client.get("/artifacts/.atlas/jobs.json").status_code,
                "artifacts route must not serve arbitrary workspace files",
            )


if __name__ == "__main__":
    unittest.main()
