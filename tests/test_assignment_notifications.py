"""Inbox actionability (audit-3): assignment notifications must identify
their subject, and every Open action must land on the exact object or a
persistent, server-resolved assignment batch.

The batch contract: /policy?assignment=<correlation>&scope=<scope>,
resolved from the audited assignment annotations — shareable, restart-
persistent, permission-checked, and never an unbounded subject list in
a URL or browser-local state.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in


def _subjects(client, limit=None) -> list[str]:
    """Real policy-result subjects straight from the rendered page."""

    page = client.get("/policy?scope=all&per_page=100").get_data(as_text=True)
    found = re.findall(r'value="(policy-result:[^"]+)"', page)
    ordered = list(dict.fromkeys(found))
    return ordered[:limit] if limit else ordered


def _assign(client, subjects, owner="alice", next_url="/policy?scope=all"):
    return client.post("/policy/assign", data={
        "owner": owner, "subjects": subjects, "next": next_url,
    }, follow_redirects=True)


def _notifications(workdir, username):
    from founderos_atlas.notifications import NotificationStore

    return NotificationStore(workdir / "workspace").for_principal(
        username, (), include_done=True,
    )


class SingleAssignmentTests(unittest.TestCase):
    def test_notification_names_policy_device_verdict_and_assigner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subject = _subjects(client, 1)[0]
            _assign(client, [subject])
            notes = _notifications(workdir, "alice")
            self.assertEqual(1, len(notes))
            note = notes[0]
            _, policy_id, hostname = subject.split(":", 2)
            self.assertIn("Policy assigned:", note.title)
            self.assertIn(hostname, note.title.casefold())
            self.assertIn("severity", note.detail)
            self.assertIn("Assigned by local-operator", note.detail)
            self.assertIn("Enterprise", note.detail)

    def test_open_link_reaches_the_exact_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subject = _subjects(client, 1)[0]
            _assign(client, [subject])
            note = _notifications(workdir, "alice")[0]
            self.assertIn("/policy/result/", note.href)
            self.assertIn("scope=", note.href)
            page = client.get(note.href)
            self.assertEqual(200, page.status_code)
            body = page.get_data(as_text=True)
            _, policy_id, hostname = subject.split(":", 2)
            self.assertIn(policy_id, body)
            self.assertIn(hostname, body.casefold())


class BulkAssignmentTests(unittest.TestCase):
    def test_bulk_creates_one_concise_notification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subjects = _subjects(client, 5)
            self.assertGreaterEqual(len(subjects), 5)
            _assign(client, subjects)
            notes = _notifications(workdir, "alice")
            self.assertEqual(1, len(notes))
            note = notes[0]
            self.assertIn("5 policy results assigned to you", note.title)
            self.assertIn("and 2 more", note.detail)
            self.assertIn("Assigned by local-operator", note.detail)
            # Preview shows the first three, separated by semicolons.
            self.assertGreaterEqual(note.detail.count(";"), 2)

    def test_bulk_open_shows_exactly_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subjects = _subjects(client, 5)
            _assign(client, subjects)
            note = _notifications(workdir, "alice")[0]
            self.assertIn("assignment=bulk%3A", note.href.replace(
                "assignment=bulk:", "assignment=bulk%3A"
            ))
            page = client.get(note.href).get_data(as_text=True)
            self.assertIn("Assignment received", page)
            # Exactness: every rendered row is a batch member (a subject
            # is policy×hostname, so one subject may evaluate in more
            # than one network — each of those rows carries the batch).
            total = int(re.search(r"(\d+) result\(s\) match", page).group(1))
            self.assertGreaterEqual(total, 5)
            self.assertEqual(total, page.count('class="row-assigned"'))
            self.assertIn("Clear assignment filter", page)

    def test_long_bulk_notification_stays_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subjects = _subjects(client)
            self.assertGreater(len(subjects), 5)
            _assign(client, subjects)
            note = _notifications(workdir, "alice")[0]
            self.assertIn(
                f"{len(subjects)} policy results assigned", note.title
            )
            # Three previews and a remainder — never the whole list.
            self.assertLess(len(note.detail), 600)
            self.assertIn(f"and {len(subjects) - 3} more", note.detail)


class FilterContractTests(unittest.TestCase):
    def test_owner_and_batch_filters_ride_pagination_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subjects = _subjects(client, 3)
            _assign(client, subjects, owner="alice")
            note = _notifications(workdir, "alice")[0]
            correlation = note.href.split("assignment=")[1].split("&")[0]
            page = client.get(
                "/policy?scope=all&owner=alice&per_page=1"
            ).get_data(as_text=True)
            # Pagination links must carry the filter.
            self.assertIn("owner=alice", page.split('rel="next"')[0][-400:]
                          if 'rel="next"' in page else page)
            self.assertIn("owner=alice", page)
            # Export carries every active filter too.
            export = client.get(
                f"/policy/export.csv?scope=all&assignment={correlation}"
            ).get_data(as_text=True)
            self.assertEqual(3, max(0, len(export.strip().splitlines()) - 1))

    def test_assignment_filter_survives_a_server_restart(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)
            subjects = _subjects(client, 2)
            _assign(client, subjects)
            note = _notifications(workdir, "alice")[0]
            # A fresh process on the same workspace resolves the batch.
            fresh_app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            fresh_app.config.update(TESTING=True)
            page = fresh_app.test_client().get(note.href).get_data(
                as_text=True
            )
            self.assertIn("Assignment received", page)
            self.assertIn("2 result(s) match", page)

    def test_mine_resolves_from_the_principal_not_the_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subjects = _subjects(client, 2)
            # Local mode: the acting principal is local-operator.
            _assign(client, subjects, owner="local-operator")
            mine = client.get("/policy?scope=all&mine=1").get_data(
                as_text=True
            )
            self.assertIn("2 result(s) match", mine)
            # A client-supplied owner can be a FILTER, but mine=1 must win
            # from the authenticated principal, never from the URL.
            spoofed = client.get(
                "/policy?scope=all&mine=1&owner=somebody-else"
            ).get_data(as_text=True)
            self.assertIn("2 result(s) match", spoofed)

    def test_empty_batch_explains_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            page = client.get(
                "/policy?scope=all&assignment=bulk:doesnotexist"
            ).get_data(as_text=True)
            self.assertIn("No result currently carries this assignment",
                          page)
            self.assertIn("audit log", page)


class ReassignmentTests(unittest.TestCase):
    def test_reassignment_is_shown_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subjects = _subjects(client, 2)
            _assign(client, subjects, owner="alice")
            alice_note = _notifications(workdir, "alice")[0]
            # One result moves on to bob after the notification existed.
            _assign(client, [subjects[0]], owner="bob")
            # The historical notification text is never rewritten...
            unchanged = _notifications(workdir, "alice")[0]
            self.assertEqual(alice_note.title, unchanged.title)
            self.assertEqual(alice_note.detail, unchanged.detail)
            # ...and opening it says what changed since.
            page = client.get(alice_note.href).get_data(as_text=True)
            self.assertIn("Assignment received", page)
            self.assertIn("1 of the originally assigned", page)
            self.assertIn("reassigned", page)

    def test_identical_repeat_assignment_makes_no_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subject = _subjects(client, 1)[0]
            _assign(client, [subject], owner="alice")
            _assign(client, [subject], owner="alice")
            self.assertEqual(1, len(_notifications(workdir, "alice")))
            # A genuinely new assignment (owner changed) notifies again.
            _assign(client, [subject], owner="bob")
            self.assertEqual(1, len(_notifications(workdir, "bob")))


class EncodingAndBoundsTests(unittest.TestCase):
    def test_special_characters_never_break_the_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            weird = 'policy-result:AT-01:host &name=?#x'
            response = _assign(client, [weird], owner="alice")
            self.assertEqual(200, response.status_code)
            note = _notifications(workdir, "alice")[0]
            # The subject no longer resolves to a row, so the link is the
            # batch filter — correlation ids are hex, inherently URL-safe.
            self.assertNotIn(" ", note.href)
            self.assertNotIn("#x", note.href)
            self.assertEqual(200, client.get(note.href).status_code)

    def test_notification_lifecycle_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            subject = _subjects(client, 1)[0]
            _assign(client, [subject], owner="local-operator")
            note = _notifications(workdir, "local-operator")[0]
            inbox = client.get("/inbox").get_data(as_text=True)
            self.assertIn("Policy assigned:", inbox)
            client.post(f"/inbox/{note.notification_id}",
                        data={"status": "read"})
            client.post(f"/inbox/{note.notification_id}",
                        data={"status": "done"})
            self.assertNotIn(
                "Policy assigned:",
                client.get("/inbox").get_data(as_text=True),
            )
            self.assertIn(
                "Policy assigned:",
                client.get("/inbox?done=1").get_data(as_text=True),
            )


class MultiUserSecurityTests(unittest.TestCase):
    def test_two_users_see_only_their_own_notifications(self) -> None:
        with production_world() as (app, workdir):
            policy_client, policy_csrf = sign_in(app, "policy")
            policy_client.post("/policy/assign", data={
                "_csrf": policy_csrf, "owner": "viewer",
                "subjects": ["policy-result:AT-01:core-1"],
                "next": "/policy?scope=all",
            })
            viewer, _ = sign_in(app, "viewer")
            operator, _ = sign_in(app, "operator")
            self.assertIn(
                "assigned",
                viewer.get("/inbox").get_data(as_text=True),
            )
            self.assertNotIn(
                "assigned to you",
                operator.get("/inbox").get_data(as_text=True),
            )

    def test_unauthenticated_batch_access_fails_closed(self) -> None:
        with production_world() as (app, _workdir):
            anonymous = app.test_client()
            response = anonymous.get(
                "/policy?assignment=bulk:guess&scope=all"
            )
            self.assertIn(response.status_code, (302, 401, 403))

    def test_mine_filter_works_in_password_mode(self) -> None:
        with production_world() as (app, _workdir):
            viewer, _ = sign_in(app, "viewer")
            page = viewer.get("/policy?scope=all&mine=1")
            self.assertEqual(200, page.status_code)
            self.assertIn("assigned to me", page.get_data(as_text=True))

    def test_mine_filter_works_in_proxy_mode(self) -> None:
        from unittest.mock import patch

        from founderos_atlas.access import UserStore
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True)
            UserStore(workspace).create(
                username="sso-vera", roles=("viewer",)
            )
            with patch.dict("os.environ", {
                "ATLAS_PROXY_SECRET": "proxy-shared-secret-1",
            }):
                app = create_app(
                    output_dir=tmp, workspace_root=workspace,
                    auth_mode="proxy",
                )
            app.config.update(TESTING=True)
            page = app.test_client().get(
                "/policy?scope=all&mine=1",
                headers={
                    "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
                    "X-Atlas-Remote-User": "sso-vera",
                },
            )
            self.assertEqual(200, page.status_code)
            self.assertIn("assigned to me", page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
