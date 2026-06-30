"""Focused repository and Project State foundation tests."""

from __future__ import annotations

import unittest

from founderos_runtime import ConflictError
from founderos_runtime.events import build_event

from tests.helpers import HUMAN, RuntimeFixture


class RuntimeFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = RuntimeFixture()

    def test_project_state_rejects_stale_detail_update(self) -> None:
        with self.assertRaises(ConflictError):
            self.fx.projects.update_details(
                self.fx.project["id"],
                expected_revision=99,
                actor=HUMAN,
                correlation_id="stale-project-update",
                next_action="Should not persist",
            )
        self.assertEqual(self.fx.refresh_project()["revision"], 1)

    def test_event_repository_rejects_sequence_gaps(self) -> None:
        event = build_event(
            self.fx.repositories,
            project_id=self.fx.project["id"],
            event_type="project.updated",
            actor=HUMAN,
            subject_ref={"kind": "project", "id": self.fx.project["id"], "revision": 1},
            correlation_id="gap",
            payload={"revision": 1},
        )
        event["sequence"] += 1
        with self.assertRaises(ConflictError):
            self.fx.repositories.events.append(event)

    def test_repository_reads_are_defensive_copies(self) -> None:
        loaded = self.fx.repositories.projects.get(self.fx.project["id"])
        loaded["name"] = "Mutated outside repository"
        self.assertNotEqual(
            self.fx.repositories.projects.get(self.fx.project["id"])["name"], loaded["name"]
        )


if __name__ == "__main__":
    unittest.main()
