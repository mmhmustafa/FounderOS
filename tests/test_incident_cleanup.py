"""Incidents cleanup: resolved hidden by default, bulk actions, and the
duplicate guard.

Cleanup never deletes: resolved and suppressed cases keep their evidence,
annotations, and audit trail — the default list simply shows active work,
with everything else one labelled click away. Re-running an identical
investigation refreshes the existing open case's evidence instead of
spawning another copy.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


def _open_case(client, title="Users behind A2 offline"):
    page = client.get("/incidents?scope=all").get_data(as_text=True)
    profile = re.search(r'name="profile".*?value="([^"]+)"', page, re.DOTALL)
    response = client.post("/incidents/run", data={
        "profile": profile.group(1) if profile else "",
        "title": title, "description": "no internet on VLAN 10",
        "severity": "medium",
    }, follow_redirects=True)
    assert b"Incident" in response.data or b"case" in response.data
    match = re.search(r"CASE-[0-9a-f]{10}", response.request.path or "")
    if match:
        return match.group(0)
    body = response.get_data(as_text=True)
    found = re.findall(r"CASE-[0-9a-f]{10}", body)
    return found[0] if found else None


class DuplicateGuardTests(unittest.TestCase):
    def test_rerun_attaches_to_the_open_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _open_case(client)
            second = client.post("/incidents/run", data={
                "profile": self._profile(client),
                "title": "Users behind A2 offline",
                "description": "still down",
            }, follow_redirects=True)
            self.assertIn(b"no duplicate case was created", second.data)
            page = client.get("/incidents?scope=all").get_data(as_text=True)
            self.assertEqual(
                1, page.count("<strong>Users behind A2 offline</strong>"),
                "the same investigation must not open a second case",
            )

    def test_resolved_case_does_not_block_a_new_one(self) -> None:
        from founderos_atlas.incidents.records import (
            IncidentCaseRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            _open_case(client)
            repo = IncidentCaseRepository(workdir / "workspace")
            case = repo.list()[0]
            repo.resolve(case.case_id, resolution="fixed",
                         actor="local-operator")
            # A recurrence after resolution is a genuinely new event.
            client.post("/incidents/run", data={
                "profile": self._profile(client),
                "title": "Users behind A2 offline",
                "description": "it came back",
            }, follow_redirects=True)
            self.assertEqual(2, len(repo.list()))

    def _profile(self, client) -> str:
        page = client.get("/incidents?scope=all").get_data(as_text=True)
        match = re.search(
            r'name="profile".*?value="([^"]+)"', page, re.DOTALL
        )
        return match.group(1) if match else ""


class ResolvedHiddenTests(unittest.TestCase):
    def test_resolved_leave_the_default_list_with_an_honest_note(self) -> None:
        from founderos_atlas.incidents.records import (
            IncidentCaseRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            _open_case(client)
            repo = IncidentCaseRepository(workdir / "workspace")
            case = repo.list()[0]
            repo.resolve(case.case_id, resolution="fixed",
                         actor="local-operator")
            page = client.get("/incidents?scope=all").get_data(as_text=True)
            self.assertIn("0 case(s) match", page)
            self.assertIn("1 resolved case(s) hidden", page)
            shown = client.get(
                "/incidents?scope=all&resolved=1"
            ).get_data(as_text=True)
            self.assertIn("Users behind A2 offline", shown)


class BulkActionTests(unittest.TestCase):
    def test_bulk_resolve_is_one_audited_action(self) -> None:
        from founderos_atlas.incidents.records import (
            IncidentCaseRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            _open_case(client, title="case one")
            _open_case(client, title="case two")
            repo = IncidentCaseRepository(workdir / "workspace")
            ids = [case.case_id for case in repo.list()]
            self.assertEqual(2, len(ids))
            response = client.post("/incidents/bulk", data={
                "bulk_action": "resolve", "case_ids": ids,
                "reason": "fixed by fw change",
                "next": "/incidents?scope=all",
            }, follow_redirects=True)
            self.assertIn(b"2 case(s) resolved", response.data)
            for case in repo.list():
                self.assertEqual("resolved", case.status)
                self.assertEqual("fixed by fw change", case.resolution)
            # One correlation id ties the batch together in the audit log.
            audit = client.get(
                "/audit?category=incident"
            ).get_data(as_text=True)
            correlations = set(re.findall(r"bulk:[0-9a-f]{32}", audit))
            self.assertEqual(1, len(correlations))

    def test_bulk_requires_a_reason_and_a_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            case_id = _open_case(client, title="needs reason")
            no_reason = client.post("/incidents/bulk", data={
                "bulk_action": "suppress", "case_ids": [case_id or "x"],
            }, follow_redirects=True)
            self.assertIn(b"reason is required", no_reason.data)
            nothing = client.post("/incidents/bulk", data={
                "bulk_action": "resolve", "reason": "r",
            }, follow_redirects=True)
            self.assertIn(b"Select at least one case", nothing.data)


if __name__ == "__main__":
    unittest.main()
