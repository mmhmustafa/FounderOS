"""The persistent case workspace unifies Atlas operational artifacts."""

from __future__ import annotations

import tempfile
import unittest

from founderos_atlas.incidents.records import (
    STATUS_ACKNOWLEDGED,
    STATUS_CLOSED,
    STATUS_INVESTIGATING,
    STATUS_MITIGATING,
    STATUS_RESOLVED,
    IncidentCaseRepository,
)


class UnifiedCaseWorkspaceTests(unittest.TestCase):
    def test_case_links_every_supported_operational_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = IncidentCaseRepository(tmp)
            case = repository.open_case(
                scope_id="enterprise",
                scope_label="Enterprise",
                title="Site unreachable",
            )
            for kind, value in (
                ("path", "delhi-edge->wan"),
                ("prediction", "prediction:1"),
                ("plan", "plan:1"),
                ("action", "note:1"),
                ("evidence", "evidence:sha256"),
                ("configuration", "config:r1:v2"),
                ("policy", "policy-result:ntp:r1"),
                ("site", "delhi"),
            ):
                repository.link(
                    case.case_id,
                    kind=kind,
                    value=value,
                    actor="alice",
                )
            loaded = IncidentCaseRepository(tmp).get(case.case_id)
            self.assertEqual(("note:1",), loaded.linked_actions)
            self.assertEqual(("evidence:sha256",), loaded.linked_evidence)
            self.assertEqual(("config:r1:v2",), loaded.linked_configurations)
            self.assertEqual(("policy-result:ntp:r1",), loaded.linked_policies)
            self.assertEqual(("delhi",), loaded.affected_sites)

    def test_explicit_lifecycle_rejects_invalid_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = IncidentCaseRepository(tmp)
            case = repository.open_case(
                scope_id="enterprise",
                scope_label="Enterprise",
                title="BGP loss",
            )
            with self.assertRaisesRegex(ValueError, "cannot move"):
                repository.transition(
                    case.case_id,
                    status=STATUS_MITIGATING,
                    actor="alice",
                    reason="skip investigation",
                )
            acknowledged = repository.transition(
                case.case_id,
                status=STATUS_ACKNOWLEDGED,
                actor="alice",
                reason="accepted",
            )
            investigating = repository.transition(
                case.case_id,
                status=STATUS_INVESTIGATING,
                actor="alice",
                reason="collecting evidence",
                expected_revision=repository.revision(),
            )
            self.assertEqual(STATUS_INVESTIGATING, investigating.status)
            self.assertNotEqual(acknowledged.updated_at, "")

    def test_close_requires_validation_or_explicit_unavailable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = IncidentCaseRepository(tmp)
            case = repository.open_case(
                scope_id="enterprise",
                scope_label="Enterprise",
                title="Interface errors",
            )
            resolved = repository.resolve(
                case.case_id,
                resolution="Replaced failed optic",
                actor="alice",
            )
            self.assertEqual(STATUS_RESOLVED, resolved.status)
            with self.assertRaisesRegex(ValueError, "validation"):
                repository.close(
                    case.case_id,
                    actor="alice",
                    reason="done",
                )
            # Re-resolving enriches the same case with validation.
            resolved = repository.resolve(
                case.case_id,
                resolution="Replaced failed optic",
                actor="alice",
                validation_evidence=("telemetry:errors-zero",),
                outstanding_risks=("Monitor replacement optic",),
                follow_up_actions=("Review vendor batch",),
            )
            closed = repository.close(
                case.case_id,
                actor="alice",
                reason="validated for 30 minutes",
                expected_revision=repository.revision(),
            )
            self.assertEqual(STATUS_CLOSED, closed.status)
            self.assertTrue(closed.closed_at)

    def test_participants_and_unlink_use_optimistic_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = IncidentCaseRepository(tmp)
            case = repository.open_case(
                scope_id="enterprise",
                scope_label="Enterprise",
                title="Latency",
            )
            updated = repository.set_participants(
                case.case_id,
                participants=("Bob", "alice", "alice"),
                actor="owner",
                expected_revision=repository.revision(),
            )
            self.assertEqual(("alice", "Bob"), updated.participants)
            repository.link(
                case.case_id, kind="evidence", value="ev:1", actor="owner"
            )
            without = repository.unlink(
                case.case_id,
                kind="evidence",
                value="ev:1",
                actor="owner",
                expected_revision=repository.revision(),
            )
            self.assertEqual((), without.linked_evidence)


if __name__ == "__main__":
    unittest.main()
