"""Unified incident/case workspace lifecycle and web integration."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from founderos_atlas.incidents.records import (
    IncidentCaseRepository,
    IncidentConflictError,
)
from tests.test_incident_cleanup import _open_case
from tests.test_polish import build_world


class CaseRepositoryLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = IncidentCaseRepository(self.root)
        self.case = self.repo.open_case(
            scope_id="lab",
            scope_label="Lab",
            title="Core path unstable",
            description="Users report intermittent loss",
            severity="high",
            actor="alice",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def transition(self, status: str):
        self.case = self.repo.transition(
            self.case.case_id,
            status=status,
            actor="alice",
            reason=f"move to {status}",
            expected_revision=self.repo.revision(),
        )

    def test_full_operational_lifecycle_and_closure_guard(self) -> None:
        for status in (
            "acknowledged", "investigating", "mitigating", "monitoring",
        ):
            self.transition(status)
            self.assertEqual(status, self.case.status)

        with self.assertRaisesRegex(ValueError, "reason validation"):
            # Direct resolve is backward compatible, but closure still fails
            # closed until validation or an explicit unavailable reason exists.
            self.case = self.repo.resolve(
                self.case.case_id,
                resolution="route policy corrected",
                actor="alice",
                expected_revision=self.repo.revision(),
            )
            self.repo.close(
                self.case.case_id,
                actor="alice",
                reason="monitoring complete",
                expected_revision=self.repo.revision(),
            )

        self.case = self.repo.reopen(
            self.case.case_id,
            reason="record validation",
            actor="alice",
            expected_revision=self.repo.revision(),
        )
        self.case = self.repo.resolve(
            self.case.case_id,
            resolution="route policy corrected",
            validation_evidence=("path run PATH-22 passed",),
            outstanding_risks=("legacy peer remains",),
            follow_up_actions=("replace peer by 2026-09-01",),
            actor="alice",
            expected_revision=self.repo.revision(),
        )
        self.case = self.repo.close(
            self.case.case_id,
            actor="alice",
            reason="validation passed and owner accepted residual risk",
            expected_revision=self.repo.revision(),
        )
        self.assertEqual("closed", self.case.status)
        self.assertTrue(self.case.closed_at)

    def test_participants_links_unlink_and_conflicts_are_audited(self) -> None:
        old_revision = self.repo.revision()
        self.case = self.repo.set_participants(
            self.case.case_id,
            participants=("netops", "secops", "netops", ""),
            actor="alice",
            expected_revision=old_revision,
        )
        self.assertEqual(("netops", "secops"), self.case.participants)
        with self.assertRaises(IncidentConflictError):
            self.repo.link(
                self.case.case_id,
                kind="policy",
                value="STD-AAA-001|edge-01",
                actor="bob",
                expected_revision=old_revision,
            )
        self.case = self.repo.link(
            self.case.case_id,
            kind="policy",
            value="STD-AAA-001|edge-01",
            actor="bob",
            expected_revision=self.repo.revision(),
        )
        self.assertIn("STD-AAA-001|edge-01", self.case.linked_policies)
        self.case = self.repo.unlink(
            self.case.case_id,
            kind="policy",
            value="STD-AAA-001|edge-01",
            actor="bob",
            expected_revision=self.repo.revision(),
        )
        self.assertFalse(self.case.linked_policies)
        with self.assertRaisesRegex(ValueError, "not linked"):
            self.repo.unlink(
                self.case.case_id,
                kind="policy",
                value="STD-AAA-001|edge-01",
                actor="bob",
                expected_revision=self.repo.revision(),
            )
        audit = (self.root / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn("set-participants", audit)
        self.assertIn("link-policy", audit)
        self.assertIn("unlink-policy", audit)
        self.assertIn('"participants": ["netops", "secops"]', audit)

    def test_legacy_document_loads_with_empty_workspace_fields(self) -> None:
        legacy = self.case.to_dict()
        for key in (
            "participants", "affected_sites", "linked_actions",
            "linked_evidence", "linked_configurations", "linked_policies",
            "validation_evidence", "validation_unavailable_reason",
            "outstanding_risks", "follow_up_actions", "closed_at",
        ):
            legacy.pop(key)
        self.repo.path.write_text(json.dumps({
            "schema_version": "1.0.0",
            "revision": 1,
            "cases": [legacy],
        }), encoding="utf-8")
        loaded = self.repo.get(self.case.case_id)
        self.assertEqual((), loaded.participants)
        self.assertEqual((), loaded.linked_policies)
        self.assertIsNone(loaded.closed_at)


class CaseWorkspaceBrowserTests(unittest.TestCase):
    def test_workspace_transitions_links_validation_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _service, client = build_world(workdir)
            case_id = _open_case(client, title="Unified case")
            self.assertIsNotNone(case_id)
            repo = IncidentCaseRepository(workdir / "workspace")

            page = client.get(
                f"/incidents/case/{case_id}"
            ).get_data(as_text=True)
            self.assertIn("Case ownership and lifecycle", page)
            self.assertIn("Participants and watchers", page)
            self.assertIn("Linked case material", page)
            self.assertIn("Resolve with validation", page)

            updated = client.post(
                f"/incidents/case/{case_id}/action",
                data={
                    "action": "participants",
                    "participants": "netops\nsecops\nnetops",
                    "expected_revision": str(repo.revision()),
                },
            )
            self.assertEqual(302, updated.status_code)
            self.assertEqual(
                ("netops", "secops"), repo.get(case_id).participants
            )

            for status in (
                "acknowledged", "investigating", "mitigating", "monitoring",
            ):
                response = client.post(
                    f"/incidents/case/{case_id}/action",
                    data={
                        "action": "transition",
                        "status": status,
                        "reason": f"operator moved to {status}",
                        "expected_revision": str(repo.revision()),
                    },
                )
                self.assertEqual(302, response.status_code)
                self.assertEqual(status, repo.get(case_id).status)

            linked = client.post(
                f"/incidents/case/{case_id}/link",
                data={
                    "kind": "policy",
                    "value": "STD-AAA-001|GW",
                    "expected_revision": str(repo.revision()),
                },
            )
            self.assertEqual(302, linked.status_code)
            page = client.get(
                f"/incidents/case/{case_id}"
            ).get_data(as_text=True)
            self.assertIn("/policy/result/STD-AAA-001/GW", page)

            resolved = client.post(
                f"/incidents/case/{case_id}/action",
                data={
                    "action": "resolve",
                    "resolution": "AAA configuration restored",
                    "validation_evidence": "policy result now passes",
                    "outstanding_risks": "legacy fallback remains",
                    "follow_up_actions": "remove fallback next window",
                    "expected_revision": str(repo.revision()),
                },
            )
            self.assertEqual(302, resolved.status_code)
            closed = client.post(
                f"/incidents/case/{case_id}/action",
                data={
                    "action": "close",
                    "reason": "validation accepted",
                    "expected_revision": str(repo.revision()),
                },
            )
            self.assertEqual(302, closed.status_code)
            self.assertEqual("closed", repo.get(case_id).status)

            # A fresh app instance reads the same durable case state.
            from founderos_atlas.web import create_app
            from tests.test_profile_isolation import make_service

            restarted_app = create_app(
                profile_service=make_service(workdir),
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            restarted_app.config.update(TESTING=True)
            restarted = restarted_app.test_client()
            restarted_page = restarted.get(
                f"/incidents/case/{case_id}"
            ).get_data(as_text=True)
            self.assertIn("Closed", restarted_page)
            self.assertIn("policy result now passes", restarted_page)
            self.assertIn("remove fallback next window", restarted_page)

    def test_unlink_requires_signed_confirmation_and_stale_link_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _service, client = build_world(workdir)
            case_id = _open_case(client, title="Unlink safety")
            repo = IncidentCaseRepository(workdir / "workspace")
            client.post(f"/incidents/case/{case_id}/link", data={
                "kind": "evidence",
                "value": "frr:GW|abc123",
                "expected_revision": str(repo.revision()),
            })
            stale = repo.revision() - 1
            conflict = client.post(f"/incidents/case/{case_id}/link", data={
                "kind": "configuration",
                "value": "frr:GW|def456",
                "expected_revision": str(stale),
            })
            self.assertEqual(409, conflict.status_code)

            first = client.post(
                f"/incidents/case/{case_id}/unlink",
                data={
                    "kind": "evidence",
                    "value": "frr:GW|abc123",
                    "expected_revision": str(repo.revision()),
                },
            )
            self.assertEqual(200, first.status_code)
            self.assertIn(b"source record is not deleted", first.data)
            self.assertIn(
                "frr:GW|abc123", repo.get(case_id).linked_evidence
            )
            body = first.get_data(as_text=True)
            token = re.search(
                r'name="_confirm_token" value="([^"]+)"', body
            ).group(1)
            confirmed = client.post(
                f"/incidents/case/{case_id}/unlink",
                data={
                    "_confirm_token": token,
                    "kind": "evidence",
                    "value": "frr:GW|abc123",
                    "expected_revision": str(repo.revision()),
                },
            )
            self.assertEqual(302, confirmed.status_code)
            self.assertFalse(repo.get(case_id).linked_evidence)


if __name__ == "__main__":
    unittest.main()
