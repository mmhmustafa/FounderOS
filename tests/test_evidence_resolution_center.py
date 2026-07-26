"""Evidence coverage and operator-guided resolution acceptance tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.evidence_resolution import (
    ResolutionDecisionConflictError,
    ResolutionDecisionRepository,
    build_resolution_queue,
    coverage_dimensions,
    filter_resolution_queue,
)
from founderos_atlas.identity import PeerResolutionRepository


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def record(**overrides):
    value = {
        "device_id": "ios:r1",
        "hostname": "r1",
        "command": "show version",
        "source": "cli",
        "collected_at": NOW.isoformat(),
        "collection_status": "collected",
        "parser_version": "2026.07",
        "discovery_session": "session-1",
        "content_sha256": "a" * 64,
        "transport": "ssh",
        "platform": "IOS",
    }
    value.update(overrides)
    return value


def unresolved(peer="10.0.0.2", candidates=None):
    return {
        "peer": peer,
        "observed_via": "ospf-neighbor",
        "why_unresolved": "no discovered device owns this identity",
        "candidates": candidates or [{
            "hostname": "r2",
            "device_id": "ios:r2",
            "signal": "address-ownership",
            "detail": "10.0.0.2 is owned by r2 (Loopback0)",
            "rank": 1,
        }],
    }


class CoverageTests(unittest.TestCase):
    def test_dimensions_are_separate_and_unknown_is_not_fake_zero(self) -> None:
        dimensions = coverage_dimensions(
            {"device_count": 2, "authenticated_count": 1},
            [record(), record(
                device_id="ios:r2", hostname="r2",
                collection_status="unavailable",
            )],
            [{
                "device_id": "ios:r1",
                "config_sha256": "b" * 64,
            }],
            {
                "counts": {
                    "relationships": 3,
                    "physical_links": 1,
                    "verified_routed_links": 0,
                    "routing_adjacencies": 1,
                    "bgp_peerings": 0,
                    "unresolved_peer_identities": 1,
                },
                "routing_view": {
                    "ospf": {"covered_devices": 1, "total_devices": 3},
                    "bgp": {"covered_devices": 0, "total_devices": 3},
                },
            },
        )
        by_key = {item["key"]: item for item in dimensions}
        self.assertIsNone(by_key["candidate-reachability"]["percent"])
        self.assertEqual("unknown", by_key["candidate-reachability"]["status"])
        self.assertEqual(50, by_key["authentication"]["percent"])
        self.assertEqual(50, by_key["configuration"]["percent"])
        self.assertEqual(50, by_key["commands"]["percent"])
        self.assertIsNone(by_key["normalized-facts"]["percent"])
        self.assertEqual(67, by_key["identity"]["percent"])


class QueueTests(unittest.TestCase):
    def test_queue_groups_collection_gaps_and_explains_identity_conflicts(self) -> None:
        candidates = [
            {
                "hostname": "r2", "device_id": "ios:r2",
                "signal": "hostname", "detail": "name match", "rank": 2,
            },
            {
                "hostname": "r2-old", "device_id": "ios:r2-old",
                "signal": "hostname", "detail": "alias match", "rank": 2,
            },
        ]
        items = build_resolution_queue(
            unresolved=[unresolved(candidates=candidates)],
            records=[
                record(
                    collection_status="error", command="show bgp summary",
                    device_id="ios:r1",
                ),
                record(
                    collection_status="error", command="show bgp summary",
                    device_id="ios:r2", hostname="r2",
                ),
            ],
            snapshots=[],
            now=NOW,
        )
        identity = next(item for item in items if item["kind"] == "identity")
        self.assertEqual(["r2", "r2-old"], identity["conflicts"])
        self.assertFalse(identity["proposals"][0]["auto_eligible"])
        failure = next(
            item for item in items if item["kind"] == "collection-failure"
        )
        self.assertEqual(2, failure["occurrences"])
        self.assertEqual(("ios:r1", "ios:r2"), failure["devices"])
        self.assertTrue(any(
            item["kind"] == "missing-configuration" for item in items
        ))

    def test_filtering_searches_devices_and_proposals(self) -> None:
        items = build_resolution_queue(
            unresolved=[unresolved()],
            records=[record()],
            snapshots=[{"device_id": "ios:r1", "config_sha256": "b" * 64}],
            now=NOW,
        )
        self.assertEqual(
            1, len(filter_resolution_queue(items, query="Loopback0"))
        )
        self.assertEqual(
            1, len(filter_resolution_queue(items, kind="identity"))
        )
        self.assertEqual(
            (), filter_resolution_queue(items, status="rejected")
        )


class DecisionPersistenceTests(unittest.TestCase):
    def test_decision_persists_conflicts_and_undo_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResolutionDecisionRepository(tmp)
            catalog, _ = repo.decide(
                item_key="identity:abc",
                status="deferred",
                reason="Awaiting circuit owner",
                actor="alice",
                expected_revision=0,
                occurred_at=NOW.isoformat(),
            )
            self.assertEqual(1, catalog.revision)
            reopened = ResolutionDecisionRepository(tmp)
            self.assertEqual(
                "deferred", reopened.load().find("identity:abc").status
            )
            with self.assertRaises(ResolutionDecisionConflictError):
                reopened.decide(
                    item_key="identity:def",
                    status="rejected",
                    reason="wrong peer",
                    actor="bob",
                    expected_revision=0,
                )
            final, event = reopened.undo(
                item_key="identity:abc",
                actor="alice",
                expected_revision=1,
            )
            self.assertIsNone(final.find("identity:abc"))
            self.assertEqual("undo", event["action"])
            self.assertEqual(2, len(reopened.history("identity:abc")))
            from founderos_atlas.workspace.backup import build_manifest
            from founderos_atlas.workspace.integrity import verify_workspace

            names = {
                item["name"] for item in build_manifest(tmp)["files"]
            }
            self.assertIn("evidence-resolution-decisions.json", names)
            states = {
                item.name: item.state for item in verify_workspace(tmp)
            }
            self.assertEqual(
                "ok", states["evidence-resolution-decisions.json"]
            )
            self.assertEqual(
                "ok", states["evidence-resolution-decisions.audit.jsonl"]
            )

    def test_atomic_bulk_identity_resolution_has_one_event_per_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = PeerResolutionRepository(tmp)
            catalog, events = repo.resolve_many([
                {
                    "peer_label": "10.0.0.2",
                    "resolved_hostname": "r2",
                    "resolved_device_id": "ios:r2",
                },
                {
                    "peer_label": "10.0.0.3",
                    "resolved_hostname": "r3",
                    "resolved_device_id": "ios:r3",
                },
            ], expected_revision=0, occurred_at=NOW.isoformat())
            self.assertEqual(2, catalog.revision)
            self.assertEqual(2, len(catalog.resolutions))
            self.assertEqual(2, len(events))
            self.assertEqual(2, len(PeerResolutionRepository(tmp).history()))


class ResolutionCenterPageTests(unittest.TestCase):
    def _client(self, root: Path):
        from founderos_atlas.enterprise_memory import EnterpriseMemoryStore
        from founderos_atlas.enterprise_memory.models import DiscoverySession
        from founderos_atlas.web import create_app

        (root / ".atlas" / "history" / "one").mkdir(parents=True)
        store = EnterpriseMemoryStore(
            root / "enterprise-memory", clock=lambda: NOW
        )
        store.begin_session(DiscoverySession(
            session_id="session-1",
            network="Lab",
            profile_id="lab",
            profile_name="Lab",
            started_at=NOW.isoformat(),
            device_count=1,
            authenticated_count=1,
        ))
        store.store_evidence(
            device_id="ios:r1",
            hostname="r1",
            command="show lldp neighbors",
            output="",
            collection_status="empty",
            discovery_session="session-1",
            source="cli",
            platform="IOS",
        )
        app = create_app(
            output_dir=root,
            history_root=root / ".atlas" / "history",
            workspace_root=root / "workspace",
        )
        app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
        return app.test_client()

    def test_page_explains_layered_coverage_and_adapter_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            body = self._client(Path(tmp)).get(
                "/evidence/resolution-center?session=session-1"
            ).get_data(as_text=True)
            self.assertIn("separate measurements", body)
            self.assertIn("Candidate reachability", body)
            self.assertIn("Normalized facts", body)
            self.assertIn("Resolution Queue", body)
            self.assertIn("independently scoped, read-only", body)
            self.assertNotIn("password", body.casefold())

    def test_decision_requires_a_reason_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._client(root)
            page = client.get(
                "/evidence/resolution-center?session=session-1"
            ).get_data(as_text=True)
            marker = 'name="item_key" value="'
            item_key = page.split(marker, 1)[1].split('"', 1)[0]
            denied = client.post(
                "/evidence/resolution-center/decision",
                data={
                    "session": "session-1",
                    "item_key": item_key,
                    "status": "deferred",
                    "expected_decision_revision": "0",
                },
            )
            self.assertEqual(302, denied.status_code)
            self.assertIsNone(
                ResolutionDecisionRepository(
                    root / "workspace"
                ).load().find(item_key)
            )
            accepted = client.post(
                "/evidence/resolution-center/decision",
                data={
                    "session": "session-1",
                    "item_key": item_key,
                    "status": "deferred",
                    "reason": "Awaiting the next maintenance window",
                    "expected_decision_revision": "0",
                },
            )
            self.assertEqual(302, accepted.status_code)
            saved = ResolutionDecisionRepository(
                root / "workspace"
            ).load().find(item_key)
            self.assertEqual("deferred", saved.status)


if __name__ == "__main__":
    unittest.main()
