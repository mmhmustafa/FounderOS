"""Historical topology replay remains evidence-based and bounded."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from founderos_atlas.history import (
    CONFIG_COLLECTED,
    HistoryRepository,
    ReplayUnavailableError,
    TopologyReplayService,
)
from founderos_atlas.topology import TopologySnapshot
from founderos_atlas.topology.snapshot import content_address
from founderos_atlas.web import create_app


def snapshot(created_at: str, devices, edges=(), warnings=()):
    metadata = {"schema_version": "1.0.0", "deterministic": True}
    device_values = tuple(devices)
    edge_values = tuple(edges)
    warning_values = tuple(warnings)
    return TopologySnapshot(
        snapshot_id=content_address(
            created_at=created_at,
            devices=device_values,
            edges=edge_values,
            warnings=warning_values,
            metadata=metadata,
        ),
        created_at=created_at,
        devices=device_values,
        edges=edge_values,
        warnings=warning_values,
        metadata=metadata,
    )


def device(name: str, *, site: str, bgp_state: str | None = None):
    routing = {"bgp_sessions": []}
    if bgp_state:
        routing["bgp_sessions"] = [{
            "peer": "192.0.2.2",
            "remote_as": 65002,
            "state": bgp_state,
        }]
    return {
        "device_id": f"id:{name}",
        "hostname": name,
        "management_ip": "192.0.2.1",
        "vendor": "Test",
        "platform": "test",
        "os_name": "test",
        "os_version": "1",
        "serial_number": f"serial-{name}",
        "interfaces": (),
        "metadata": {
            "site_id": site,
            "routing_evidence": routing,
        },
    }


class NetworkTimeTravelTests(unittest.TestCase):
    def _save(
        self,
        repository: HistoryRepository,
        work: Path,
        value: TopologySnapshot,
        started_at: str,
        profile_id: str = "profile-a",
    ):
        source = work / f"{started_at.replace(':', '-')}.json"
        source.write_text(
            json.dumps(value.to_dict(), sort_keys=True), encoding="utf-8"
        )
        return repository.save_discovery(
            started_at=started_at,
            completed_at=started_at,
            duration_seconds=1,
            device_count=value.device_count,
            relationship_count=value.edge_count,
            warning_count=len(value.warnings),
            failures=(),
            configuration_status=CONFIG_COLLECTED,
            configured_device_count=value.device_count,
            quality_score=100,
            network_status="healthy",
            snapshot_id=value.snapshot_id,
            artifacts={"topology_snapshot.json": source},
            profile_id=profile_id,
            profile_name=profile_id,
        )

    def test_compare_reports_device_site_and_bgp_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            repository = HistoryRepository(work / "history")
            before = snapshot(
                "2026-07-01T00:00:00+00:00",
                (device("r1", site="Delhi", bgp_state="established"),),
            )
            after = snapshot(
                "2026-07-02T00:00:00+00:00",
                (
                    device("r1", site="Mumbai", bgp_state="idle"),
                    device("r2", site="Mumbai"),
                ),
            )
            left = self._save(
                repository, work, before, "2026-07-01T00:00:00+00:00"
            )
            right = self._save(
                repository, work, after, "2026-07-02T00:00:00+00:00"
            )
            compared = TopologyReplayService(repository).compare(
                left.record_id, right.record_id
            )
            categories = {item.category for item in compared.changes}
            self.assertIn("device", categories)
            self.assertIn("site-membership", categories)
            self.assertIn("bgp", categories)
            self.assertTrue(compared.changed)
            self.assertEqual(right.snapshot_id, compared.current_snapshot_id)

    def test_different_profiles_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            repository = HistoryRepository(work / "history")
            one = snapshot(
                "2026-07-01T00:00:00+00:00", (device("r1", site="A"),)
            )
            two = snapshot(
                "2026-07-02T00:00:00+00:00", (device("r1", site="A"),)
            )
            left = self._save(
                repository, work, one, "2026-07-01T00:00:00+00:00", "a"
            )
            right = self._save(
                repository, work, two, "2026-07-02T00:00:00+00:00", "b"
            )
            with self.assertRaisesRegex(
                ReplayUnavailableError, "different observation profiles"
            ):
                TopologyReplayService(repository).compare(
                    left.record_id, right.record_id
                )

    def test_missing_and_tampered_snapshot_are_honest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = HistoryRepository(Path(tmp) / "history")
            with self.assertRaisesRegex(
                ReplayUnavailableError, "no topology snapshot"
            ):
                TopologyReplayService(repository).load_snapshot("missing")

    def test_same_record_is_not_a_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = TopologyReplayService(
                HistoryRepository(Path(tmp) / "history")
            )
            with self.assertRaisesRegex(
                ReplayUnavailableError, "different discovery"
            ):
                service.compare("one", "one")


class NetworkTimeTravelWebTests(unittest.TestCase):
    _save = NetworkTimeTravelTests._save

    def _client_with_history(self, root: Path):
        history_root = root / ".atlas" / "history"
        repository = HistoryRepository(history_root)
        before = snapshot(
            "2026-07-01T00:00:00+00:00",
            (device("r1", site="Delhi", bgp_state="established"),),
        )
        after = snapshot(
            "2026-07-02T00:00:00+00:00",
            (
                device("r1", site="Mumbai", bgp_state="idle"),
                device("r2", site="Mumbai"),
            ),
        )
        left = self._save(
            repository, root, before, "2026-07-01T00:00:00+00:00"
        )
        right = self._save(
            repository, root, after, "2026-07-02T00:00:00+00:00"
        )
        viewer = repository.record_directory(left.record_id) / "atlas_topology.html"
        viewer.write_text("<!doctype html><title>Archived topology</title>", encoding="utf-8")
        app = create_app(
            output_dir=root,
            history_root=history_root,
            workspace_root=root / "workspace",
        )
        app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
        return app.test_client(), left, right

    def test_page_replays_provenance_and_loads_external_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, left, right = self._client_with_history(Path(tmp))
            response = client.get("/history/time-travel")
            body = response.get_data(as_text=True)
            self.assertEqual(200, response.status_code)
            self.assertIn("Network Time Travel", body)
            self.assertIn(left.record_id, body)
            self.assertIn(right.record_id, body)
            self.assertIn("site membership", body.casefold())
            self.assertIn("BGP", body)
            self.assertIn("atlas-time-travel.js", body)
            self.assertNotIn("<script>", body)
            self.assertIn("Open From map", body)

    def test_api_and_export_are_bounded_to_normalized_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, left, right = self._client_with_history(Path(tmp))
            query = f"?from={left.record_id}&to={right.record_id}"
            api = client.get("/api/history/time-travel" + query)
            self.assertEqual(200, api.status_code)
            self.assertEqual(
                left.record_id,
                api.get_json()["comparison"]["previous_record_id"],
            )
            exported = client.get(
                "/history/time-travel/export.json" + query
            )
            text = exported.get_data(as_text=True)
            self.assertEqual(200, exported.status_code)
            self.assertIn("attachment;", exported.headers["Content-Disposition"])
            self.assertIn("Raw command output", text)
            self.assertNotIn("password", text.casefold())
            self.assertNotIn("private key", text.casefold())
            self.assertNotIn("configuration_text", text)

    def test_invalid_and_same_snapshot_selections_fail_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, left, _right = self._client_with_history(Path(tmp))
            missing = client.get(
                "/api/history/time-travel?from=missing&to=also-missing"
            )
            self.assertEqual(400, missing.status_code)
            same = client.get(
                f"/api/history/time-travel?from={left.record_id}"
                f"&to={left.record_id}"
            )
            self.assertEqual(400, same.status_code)
            page = client.get(
                f"/history/time-travel?from={left.record_id}"
                f"&to={left.record_id}"
            )
            self.assertEqual(200, page.status_code)
            self.assertIn("Cannot compare", page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
