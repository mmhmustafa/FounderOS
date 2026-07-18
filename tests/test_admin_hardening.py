"""Authentication and administrator-lockout hardening.

Covers: local-mode fail-closed behavior behind proxies, layered login
rate limiting (account/source/global) without user enumeration, the
last-administrator invariants, re-authentication for high-risk user
changes, session revocation, emergency recovery, secret hygiene, and
RBAC on every user-management endpoint.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from founderos_atlas.access import (
    LastAdministratorError,
    SESSION_COOKIE,
    UserStore,
)
from tests.test_production_security import (
    PASSWORDS,
    production_world,
    sign_in,
)


def local_app(tmp, **env):
    from founderos_atlas.web import create_app

    with patch.dict("os.environ", env, clear=False):
        app = create_app(
            output_dir=tmp, workspace_root=Path(tmp) / "ws",
        )
    app.config.update(TESTING=True)
    return app


class LocalModeProxyExposureTests(unittest.TestCase):
    FORWARDING_CASES = (
        {"X-Forwarded-For": "203.0.113.9"},
        {"Forwarded": "for=203.0.113.9"},
        {"X-Real-IP": "203.0.113.9"},
        {"True-Client-IP": "203.0.113.9"},
    )

    def test_loopback_proxy_forwarding_is_refused(self) -> None:
        """A reverse proxy on the same machine makes remote users look
        loopback; the forwarding headers it adds are the tell, and local
        mode fails closed on them."""

        with tempfile.TemporaryDirectory() as tmp:
            client = local_app(tmp).test_client()
            for headers in self.FORWARDING_CASES:
                response = client.get(
                    "/", headers=headers,
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
                with self.subTest(header=next(iter(headers))):
                    self.assertEqual(403, response.status_code)
                    self.assertIn(b"refuses proxied requests", response.data)

    def test_direct_local_development_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = local_app(tmp).test_client()
            response = client.get(
                "/", environ_base={"REMOTE_ADDR": "127.0.0.1"}
            )
            self.assertEqual(200, response.status_code)

    def test_explicit_narrow_override_admits_local_dev_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = local_app(
                tmp, ATLAS_LOCAL_ALLOW_FORWARDED="1"
            ).test_client()
            response = client.get(
                "/", headers={"X-Forwarded-For": "203.0.113.9"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
            self.assertEqual(200, response.status_code)
            # The override never widens beyond loopback peers.
            remote = client.get(
                "/", headers={"X-Forwarded-For": "127.0.0.1"},
                environ_base={"REMOTE_ADDR": "203.0.113.9"},
            )
            self.assertEqual(403, remote.status_code)

    def test_local_mode_refuses_to_start_with_proxy_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("ATLAS_PROXY_SECRET", "ATLAS_TRUSTED_PROXY_ADDRS"):
                with self.subTest(setting=name):
                    with self.assertRaises(RuntimeError):
                        local_app(tmp, **{name: "10.0.0.2"})


class LayeredLoginRateLimitTests(unittest.TestCase):
    def _attempt(self, client, username, addr="203.0.113.1"):
        return client.post(
            "/login",
            data={"username": username, "password": "wrong-password-xx"},
            environ_base={"REMOTE_ADDR": addr},
        )

    def test_distributed_attack_on_one_account_hits_account_layer(self) -> None:
        with production_world() as (app, _):
            client = app.test_client()
            # 12 rapid attempts: even if a fixed one-minute window rolls
            # over mid-test, one window is guaranteed to see six.
            statuses = [
                self._attempt(client, "admin", addr=f"203.0.113.{i}").status_code
                for i in range(1, 13)
            ]
            self.assertIn(429, statuses, "account layer never engaged")
            self.assertEqual(401, statuses[0], statuses)

    def test_case_variants_do_not_bypass_the_account_layer(self) -> None:
        with production_world() as (app, _):
            client = app.test_client()
            names = ["admin", "Admin", "ADMIN", "aDmIn", "admin", "ADMIN"] * 2
            statuses = [
                self._attempt(client, name, addr=f"198.51.100.{i}").status_code
                for i, name in enumerate(names, start=1)
            ]
            self.assertIn(429, statuses, statuses)

    def test_one_noisy_account_does_not_deny_every_other_account(self) -> None:
        with production_world() as (app, _):
            client = app.test_client()
            for i in range(1, 7):
                self._attempt(client, "viewer", addr=f"203.0.113.{i}")
            # A different account from a fresh source authenticates fine.
            ok = client.post(
                "/login",
                data={"username": "admin",
                      "password": PASSWORDS["admin"]},
                environ_base={"REMOTE_ADDR": "198.51.100.99"},
            )
            self.assertEqual(302, ok.status_code)

    def test_source_layer_caps_one_address_spraying_accounts(self) -> None:
        with production_world() as (app, _):
            client = app.test_client()
            # 70 attempts guarantee one window sees more than the
            # 30/minute source limit even across a window boundary.
            statuses = [
                self._attempt(
                    client, f"user-{i}", addr="192.0.2.7"
                ).status_code
                for i in range(70)
            ]
            self.assertIn(429, statuses, "source layer never engaged")

    def test_no_user_enumeration_in_text_or_status(self) -> None:
        with production_world() as (app, _):
            client = app.test_client()
            existing = self._attempt(client, "admin", addr="203.0.113.50")
            missing = self._attempt(
                client, "no-such-user-at-all", addr="203.0.113.51"
            )
            self.assertEqual(existing.status_code, missing.status_code)
            self.assertEqual(existing.data, missing.data)

    def test_429_is_audited_without_the_password(self) -> None:
        with production_world() as (app, workdir):
            client = app.test_client()
            for i in range(7):
                client.post("/login", data={
                    "username": "admin",
                    "password": "Sup3r-Secret-Attempt!",
                }, environ_base={"REMOTE_ADDR": f"203.0.113.{60 + i}"})
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("sign-in limit", audit)
            self.assertIn("account", audit)
            self.assertNotIn("Sup3r-Secret-Attempt!", audit)

    def test_limiter_is_single_process_and_resets_on_restart(self) -> None:
        """The built-in limiter is explicitly in-process/in-memory: its
        counters are not shared across workers and vanish on restart.
        Multi-worker deployments must configure a shared adapter."""

        from founderos_atlas.access import resolve_rate_limiter
        from founderos_atlas.access.ratelimit import RateLimiter

        self.assertEqual("single-process", RateLimiter.scope)
        first = resolve_rate_limiter()
        for _ in range(5):
            first.allow("login:acct:admin", limit=5)
        self.assertFalse(first.allow("login:acct:admin", limit=5))
        # A "restart" (new process => new limiter) starts clean.
        second = resolve_rate_limiter()
        self.assertTrue(second.allow("login:acct:admin", limit=5))
        # Unknown shared adapters refuse loudly instead of degrading.
        with patch.dict("os.environ", {"ATLAS_RATE_LIMITER": "redis"}):
            with self.assertRaises(RuntimeError):
                resolve_rate_limiter()


class LastAdministratorInvariantTests(unittest.TestCase):
    def test_store_refuses_disable_delete_demote_of_last_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserStore(tmp)
            store.create(username="root", roles=("system-admin",),
                         password="root-password-12345")
            with self.assertRaises(LastAdministratorError):
                store.update("root", disabled=True)
            with self.assertRaises(LastAdministratorError):
                store.update("root", roles=("viewer",))
            with self.assertRaises(LastAdministratorError):
                store.delete("root")
            # With a second usable admin, the same changes are legal.
            store.create(username="root2", roles=("system-admin",),
                         password="root2-password-1234")
            store.update("root", roles=("viewer",))
            self.assertEqual(("viewer",), store.get("root").roles)

    def test_sso_only_admin_counts_only_in_proxy_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserStore(tmp)
            store.create(username="root", roles=("system-admin",),
                         password="root-password-12345")
            store.create(username="sso-admin", roles=("system-admin",))
            # Password mode: the SSO-only admin cannot sign in, so it
            # does not license removing the password admin.
            with self.assertRaises(LastAdministratorError):
                store.delete("root", allow_sso_admins=False)
            # Proxy mode: SSO-only admins are fully usable.
            self.assertTrue(store.delete("root", allow_sso_admins=True))

    def test_http_self_disable_and_self_demotion_are_refused(self) -> None:
        with production_world() as (app, _):
            admin, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            disable = admin.post("/users/admin", data={
                "_csrf": csrf, "disabled": "1",
                "admin_password": PASSWORDS["admin"],
                "expected_revision": str(store.revision()),
            }, follow_redirects=True)
            self.assertIn(b"cannot disable the account you are signed in",
                          disable.data)
            self.assertFalse(store.get("admin").disabled)
            demote = admin.post("/users/admin", data={
                "_csrf": csrf, "roles": "viewer",
                "admin_password": PASSWORDS["admin"],
                "expected_revision": str(store.revision()),
            }, follow_redirects=True)
            self.assertIn(b"cannot remove your own system-admin role",
                          demote.data)
            self.assertIn("system-admin", store.get("admin").roles)
            # The signed-in admin remains fully functional afterwards.
            self.assertEqual(200, admin.get("/users").status_code)

    def test_http_last_admin_demotion_refused_when_backup_is_disabled(self) -> None:
        with production_world() as (app, _):
            admin, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            store.create(username="admin2", roles=("system-admin",),
                         password="admin2-password-123", )
            store.update("admin2", disabled=True)
            # admin2 is disabled, so demoting 'admin' would strand Atlas.
            with self.assertRaises(LastAdministratorError):
                store.update("admin", roles=("viewer",))

    def test_password_rotation_revokes_the_holders_sessions(self) -> None:
        with production_world() as (app, _):
            viewer_client, _ = sign_in(app, "viewer")
            self.assertEqual(200, viewer_client.get("/").status_code)
            admin, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            admin.post("/users/viewer", data={
                "_csrf": csrf,
                "password": "rotated-password-9876",
                "admin_password": PASSWORDS["admin"],
                "expected_revision": str(store.revision()),
            })
            # The old session no longer resolves.
            self.assertEqual(302, viewer_client.get("/").status_code)

    def test_reauth_is_required_and_wrong_password_is_refused(self) -> None:
        with production_world() as (app, workdir):
            admin, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            missing = admin.post("/users/viewer", data={
                "_csrf": csrf, "display_name": "V.",
                "expected_revision": str(store.revision()),
            }, follow_redirects=True)
            self.assertIn(b"entering your own password", missing.data)
            self.assertNotEqual("V.", store.get("viewer").display_name)
            wrong = admin.post("/users/viewer", data={
                "_csrf": csrf, "display_name": "V.",
                "admin_password": "not-my-password-123",
                "expected_revision": str(store.revision()),
            }, follow_redirects=True)
            self.assertIn(b"entering your own password", wrong.data)
            good = admin.post("/users/viewer", data={
                "_csrf": csrf, "display_name": "V.",
                "admin_password": PASSWORDS["admin"],
                "expected_revision": str(store.revision()),
            }, follow_redirects=True)
            self.assertEqual(200, good.status_code)
            self.assertEqual("V.", store.get("viewer").display_name)
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"reauth"', audit)
            self.assertNotIn("not-my-password-123", audit)

    def test_emergency_recovery_restores_a_locked_out_deployment(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True)
            # A deployment whose only account is not an administrator.
            UserStore(workspace).create(
                username="viewer-only", roles=("viewer",),
                password="viewer-password-1234",
            )
            with patch.dict("os.environ", {
                "ATLAS_RECOVERY_ADMIN_USER": "rescue",
                "ATLAS_RECOVERY_ADMIN_PASSWORD": "rescue-password-1234",
            }):
                app = create_app(
                    output_dir=tmp, workspace_root=workspace,
                    auth_mode="password",
                )
            app.config.update(TESTING=True)
            client = app.test_client()
            signed_in = client.post("/login", data={
                "username": "rescue", "password": "rescue-password-1234",
            })
            self.assertEqual(302, signed_in.status_code)
            self.assertEqual(200, client.get("/users").status_code)
            audit = (workspace / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn('"recovery-reset"', audit)
            self.assertNotIn("rescue-password-1234", audit)
            self.assertNotIn(
                "rescue-password-1234",
                (workspace / "users.json").read_text(encoding="utf-8"),
            )


class ProxyModeAdministrationTests(unittest.TestCase):
    def _proxy_app(self, tmp):
        from founderos_atlas.web import create_app

        workspace = Path(tmp) / "ws"
        workspace.mkdir(parents=True, exist_ok=True)
        store = UserStore(workspace)
        store.create(username="sso-root", roles=("system-admin",))
        store.create(username="sso-viewer", roles=("viewer",))
        with patch.dict("os.environ", {
            "ATLAS_PROXY_SECRET": "proxy-shared-secret-1",
        }):
            app = create_app(
                output_dir=tmp, workspace_root=workspace, auth_mode="proxy",
            )
        app.config.update(TESTING=True)
        return app, store

    @staticmethod
    def _headers(user):
        return {
            "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
            "X-Atlas-Remote-User": user,
        }

    def test_sso_only_admin_can_administer_and_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, store = self._proxy_app(tmp)
            client = app.test_client()
            page = client.get("/users", headers=self._headers("sso-root"))
            self.assertEqual(200, page.status_code)
            # No re-auth password exists in proxy mode; changes proceed
            # under RBAC + audit.
            update = client.post(
                "/users/sso-viewer",
                data={"display_name": "Viewer",
                      "expected_revision": str(store.revision())},
                headers=self._headers("sso-root"),
            )
            self.assertEqual(302, update.status_code)
            self.assertEqual("Viewer", store.get("sso-viewer").display_name)
            # The sole SSO-only admin is still the last usable admin.
            with self.assertRaises(LastAdministratorError):
                store.update("sso-root", disabled=True,
                             allow_sso_admins=True)

    def test_viewer_cannot_touch_user_management(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, store = self._proxy_app(tmp)
            client = app.test_client()
            headers = self._headers("sso-viewer")
            self.assertEqual(
                403, client.get("/users", headers=headers).status_code
            )
            self.assertEqual(403, client.post(
                "/users/sso-root",
                data={"disabled": "1",
                      "expected_revision": str(store.revision())},
                headers=headers,
            ).status_code)
            self.assertEqual(403, client.post(
                "/users/sso-root/delete",
                data={"expected_revision": str(store.revision())},
                headers=headers,
            ).status_code)
            self.assertFalse(store.get("sso-root").disabled)


class SecretHygieneTests(unittest.TestCase):
    def test_users_page_and_stores_never_show_password_material(self) -> None:
        with production_world() as (app, workdir):
            admin, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            admin.post("/users/viewer", data={
                "_csrf": csrf, "password": "brand-new-password-77",
                "admin_password": PASSWORDS["admin"],
                "expected_revision": str(store.revision()),
            })
            page = admin.get("/users").data.decode("utf-8")
            self.assertNotIn("brand-new-password-77", page)
            self.assertNotIn("scrypt$", page)
            for name in ("audit.jsonl", "notifications.jsonl", "users.json"):
                path = workdir / "workspace" / name
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    self.assertNotIn("brand-new-password-77", content, name)
                    self.assertNotIn(PASSWORDS["admin"], content, name)
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"password_changed": true', audit)


if __name__ == "__main__":
    unittest.main()
