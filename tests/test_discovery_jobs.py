"""Acceptance tests for PR-032 GUI-driven discovery jobs.

Discovery runs from the GUI through an in-process job manager that reuses
the exact CLI pipeline (`atlas_discover_command`) — one shared discovery
service, executed asynchronously, observed through a polled JSON API, with
PR-031A profile-scoped isolation preserved as a hard invariant.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from founderos_atlas.transport import AuthenticationError
from founderos_atlas.web import create_app
from founderos_atlas.web.jobs import DiscoveryJobManager
from founderos_atlas.workspace import ProfileRepository, ProfileService

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_profile_isolation import (
    add_profile,
    make_service,
    network_a,
    network_b,
    scope_dir,
)
from tests.test_unified_pipeline import full_outputs
from tests.test_workspace_profiles import UnavailableCredentialProvider


def combined_network() -> ScriptedNetwork:
    """Both labs' devices behind one scripted network (hosts don't overlap)."""

    return ScriptedNetwork(
        {
            "10.0.0.1": full_outputs("A1", "10.0.0.1", (("A2", "10.0.0.2"),)),
            "10.0.0.2": full_outputs("A2", "10.0.0.2", (("A1", "10.0.0.1"),)),
            "10.0.1.1": full_outputs("B1", "10.0.1.1"),
        }
    )


def poll_until(condition, timeout: float = 20.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


class GateOnHost:
    """Transport factory that blocks connections to one host until released."""

    def __init__(self, network: ScriptedNetwork, host: str) -> None:
        self.network = network
        self.host = host
        self.gate = threading.Event()

    def __call__(self, credentials):
        if credentials.host == self.host:
            assert self.gate.wait(timeout=30), "test gate was never released"
        return self.network.transport_factory(credentials.host)


def build_app(workdir: Path, service, *, transport_factory=None):
    app = create_app(
        profile_service=service,
        output_dir=workdir,
        history_root=workdir / ".atlas" / "history",
        transport_factory=transport_factory,
    )
    app.config.update(TESTING=True)
    return app, app.test_client(), app.config["ATLAS_JOB_MANAGER"]


def two_lab_world(workdir: Path, *, transport_factory=None):
    service = make_service(workdir)
    add_profile(service, "Lab A", "10.0.0.1")
    add_profile(service, "Lab B", "10.0.1.1")
    factory = transport_factory or (
        lambda c: combined_network().transport_factory(c.host)
    )
    app, client, manager = build_app(workdir, service, transport_factory=factory)
    return service, app, client, manager


class DiscoveryJobApiTests(unittest.TestCase):
    def test_api_creates_job_and_completes_with_real_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, _, client, manager = two_lab_world(workdir)
            response = client.post("/api/discovery/jobs", data={"profile": "Lab A"})
            self.assertEqual(202, response.status_code)
            payload = response.get_json()
            self.assertTrue(payload["created"])
            job_id = payload["job"]["job_id"]
            self.assertIn(payload["job"]["status"], ("queued", "running"))
            manager.wait(job_id, timeout=30)
            body = client.get(f"/api/discovery/jobs/{job_id}").get_json()
            job = body["job"]
            self.assertEqual("completed", job["status"])
            self.assertEqual(7, job["stage_number"])
            self.assertEqual(7, job["total_stages"])
            self.assertEqual(100, job["percent"])
            self.assertEqual("stages", job["progress_basis"])
            self.assertEqual(2, job["devices_discovered"])
            self.assertEqual(2, job["summary"]["devices"])
            self.assertEqual(1, job["summary"]["relationships"])
            self.assertIsNotNone(job["elapsed_seconds"])
            self.assertIsNone(job["error"])
            # Real profile-scoped artifacts exist; nothing in shared paths.
            scope = scope_dir(workdir, "lab-a")
            self.assertTrue((scope / "topology_snapshot.json").is_file())
            self.assertTrue((scope / "dashboard.html").is_file())
            self.assertFalse((workdir / "topology_snapshot.json").exists())
            self.assertIsNotNone(service.get_profile("Lab A").last_discovery)

    def test_api_requires_an_explicit_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, client, _ = two_lab_world(Path(tmp))
            response = client.post("/api/discovery/jobs", data={})
            self.assertEqual(400, response.status_code)
            self.assertIn("Select a network profile", response.get_json()["error"])

    def test_api_unknown_profile_is_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, client, _ = two_lab_world(Path(tmp))
            response = client.post("/api/discovery/jobs", data={"profile": "Nope"})
            self.assertEqual(404, response.status_code)
            self.assertIn("No saved profile named 'Nope'", response.get_json()["error"])

    def test_api_never_exposes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, _, client, manager = two_lab_world(workdir)
            create = client.post("/api/discovery/jobs", data={"profile": "Lab A"})
            job_id = create.get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            status = client.get(f"/api/discovery/jobs/{job_id}")
            listing = client.get("/api/discovery/jobs")
            for response in (create, status, listing):
                text = response.get_data(as_text=True)
                self.assertNotIn(PASSWORD, text)
                self.assertNotIn("credential_ref", text)
                self.assertNotIn("password", text.casefold())
            # The persisted job history is also secret-free.
            jobs_file = workdir / ".atlas" / "jobs.json"
            self.assertTrue(jobs_file.is_file())
            self.assertNotIn(PASSWORD, jobs_file.read_text(encoding="utf-8"))

    def test_progress_reflects_real_pipeline_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            gate = GateOnHost(combined_network(), "10.0.0.1")
            _, _, client, manager = two_lab_world(workdir, transport_factory=gate)
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            # While the seed connection is genuinely in flight, the job
            # reports the real stage and the real device being contacted.
            self.assertTrue(
                poll_until(
                    lambda: client.get(f"/api/discovery/jobs/{job_id}").get_json()[
                        "job"
                    ]["stage_number"]
                    == 2
                )
            )
            mid = client.get(f"/api/discovery/jobs/{job_id}").get_json()["job"]
            self.assertEqual("running", mid["status"])
            self.assertEqual("Connecting to seed device", mid["stage"])
            self.assertEqual("10.0.0.1", mid["current_device"])
            gate.gate.set()
            manager.wait(job_id, timeout=30)
            job = manager.get(job_id)
            # Stage progression and counts came from real pipeline lines.
            self.assertEqual(2, job.devices_discovered)
            log_text = "\n".join(job.log)
            self.assertIn("[2/9] Discovering topology ... ok (2 device(s), 0 failed)", log_text)
            self.assertIn("[9/9] Updating dashboard", log_text)
            events = client.get(f"/api/discovery/jobs/{job_id}").get_json()["job"][
                "events"
            ]
            self.assertTrue(events)

    def test_duplicate_same_profile_job_is_prevented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            gate = GateOnHost(combined_network(), "10.0.0.1")
            _, _, client, manager = two_lab_world(workdir, transport_factory=gate)
            first = client.post("/api/discovery/jobs", data={"profile": "Lab A"})
            self.assertEqual(202, first.status_code)
            first_id = first.get_json()["job"]["job_id"]
            second = client.post("/api/discovery/jobs", data={"profile": "Lab A"})
            self.assertEqual(409, second.status_code)
            body = second.get_json()
            self.assertFalse(body["created"])
            self.assertEqual(first_id, body["job"]["job_id"])
            gate.gate.set()
            manager.wait(first_id, timeout=30)
            # Once finished, a new run is allowed again.
            third = client.post("/api/discovery/jobs", data={"profile": "Lab A"})
            self.assertEqual(202, third.status_code)
            self.assertNotEqual(first_id, third.get_json()["job"]["job_id"])
            manager.wait(third.get_json()["job"]["job_id"], timeout=30)

    def test_jobs_for_different_profiles_serialize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            gate = GateOnHost(combined_network(), "10.0.0.1")
            _, _, client, manager = two_lab_world(workdir, transport_factory=gate)
            job_a = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            self.assertTrue(
                poll_until(lambda: manager.get(job_a).status == "running")
            )
            response_b = client.post("/api/discovery/jobs", data={"profile": "Lab B"})
            self.assertEqual(202, response_b.status_code)  # allowed, but queued
            job_b = response_b.get_json()["job"]["job_id"]
            time.sleep(0.2)  # give B's worker a chance to (wrongly) start
            self.assertEqual("queued", manager.get(job_b).status)
            gate.gate.set()
            manager.wait(job_a, timeout=30)
            manager.wait(job_b, timeout=30)
            self.assertEqual("completed", manager.get(job_a).status)
            self.assertEqual("completed", manager.get(job_b).status)


class DiscoveryJobFailureTests(unittest.TestCase):
    def test_authentication_failure_is_friendly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)

            def failing_factory(credentials):
                raise AuthenticationError(
                    f"Authentication failed for {credentials.host}. "
                    "Verify the username and password."
                )

            _, _, client, manager = two_lab_world(
                workdir, transport_factory=failing_factory
            )
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            job = client.get(f"/api/discovery/jobs/{job_id}").get_json()["job"]
            self.assertEqual("failed", job["status"])
            self.assertIn("Authentication failed for 10.0.0.1", job["error"])
            self.assertIn("Lab A profile", job["error"])
            self.assertNotIn("Traceback", job["error"])

    def test_connection_timeout_is_friendly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            network = ScriptedNetwork(
                {"10.0.1.1": full_outputs("B1", "10.0.1.1")},
                unreachable=frozenset({"10.0.0.1"}),
            )
            _, _, client, manager = two_lab_world(
                workdir,
                transport_factory=lambda c: network.transport_factory(c.host),
            )
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            job = client.get(f"/api/discovery/jobs/{job_id}").get_json()["job"]
            self.assertEqual("failed", job["status"])
            self.assertIn("Connection to 10.0.0.1 timed out", job["error"])
            self.assertIn("Verify the device is reachable", job["error"])
            self.assertNotIn("Traceback", job["error"])

    def test_unavailable_credential_store_is_friendly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            # The profile exists (created while a store was available), but
            # the credential backend is gone when discovery runs.
            make_creds = make_service(workdir)
            add_profile(make_creds, "Lab A", "10.0.0.1")
            broken = ProfileService(
                ProfileRepository(workdir / "workspace"),
                UnavailableCredentialProvider(),
            )
            _, client, manager = build_app(
                workdir,
                broken,
                transport_factory=lambda c: combined_network().transport_factory(
                    c.host
                ),
            )
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            job = client.get(f"/api/discovery/jobs/{job_id}").get_json()["job"]
            self.assertEqual("failed", job["status"])
            self.assertIn("Secure credential storage is unavailable", job["error"])
            self.assertIn("founderos-runtime[credentials]", job["error"])


class DiscoveryJobIsolationTests(unittest.TestCase):
    def test_gui_jobs_preserve_profile_scoped_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, _, client, manager = two_lab_world(workdir)

            def run(profile: str) -> None:
                job_id = client.post(
                    "/api/discovery/jobs", data={"profile": profile}
                ).get_json()["job"]["job_id"]
                finished = manager.wait(job_id, timeout=30)
                self.assertEqual("completed", finished.status, finished.error)

            run("Lab A")
            run("Lab B")
            scope_a, scope_b = scope_dir(workdir, "lab-a"), scope_dir(workdir, "lab-b")
            hosts_a = {
                d["hostname"]
                for d in json.loads(
                    (scope_a / "topology_snapshot.json").read_text("utf-8")
                )["devices"]
            }
            hosts_b = {
                d["hostname"]
                for d in json.loads(
                    (scope_b / "topology_snapshot.json").read_text("utf-8")
                )["devices"]
            }
            self.assertEqual({"A1", "A2"}, hosts_a)
            self.assertEqual({"B1"}, hosts_b)
            # First runs each: no cross-profile change reports anywhere.
            self.assertFalse((scope_a / "change_report.json").exists())
            self.assertFalse((scope_b / "change_report.json").exists())
            # Re-running A compares only against A's own baseline.
            snapshot_b_before = (scope_b / "topology_snapshot.json").read_bytes()
            run("Lab A")
            report = json.loads(
                (scope_a / "change_report.json").read_text("utf-8")
            )
            self.assertEqual(0, report["change_count"])
            self.assertEqual([], report["removed_devices"])
            self.assertNotIn(
                "B1", (scope_a / "change_report.md").read_text("utf-8")
            )
            # ...and B's scope is byte-for-byte untouched.
            self.assertEqual(
                snapshot_b_before, (scope_b / "topology_snapshot.json").read_bytes()
            )

    def test_job_start_focuses_gui_scope_on_that_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, _, client, manager = two_lab_world(workdir)
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab B"}
            ).get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            # Same browser session, no scope parameter: Lab B is in focus.
            page = client.get("/history").data
            self.assertIn(b"Discovery History \xe2\x80\x94 Lab B", page)

    def test_dashboard_reflects_results_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, _, client, manager = two_lab_world(workdir)
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            page = client.get("/?scope=lab-a").data
            self.assertIn(b"<span>2</span>", page)  # A1 + A2, freshly read


class DiscoverPageTests(unittest.TestCase):
    def test_page_shows_profile_details_and_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, _, client, manager = two_lab_world(workdir)
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            manager.wait(job_id, timeout=30)
            page = client.get("/discovery").data
            for expected in (b"Lab A", b"Lab B", b"10.0.0.1", b"10.0.1.1",
                             b"Seed IP", b"Last Discovery", b"completed"):
                self.assertIn(expected, page)
            self.assertNotIn(PASSWORD.encode(), page)

    def test_all_networks_requires_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, client, _ = two_lab_world(Path(tmp))
            page = client.get("/discovery?scope=all").data
            self.assertIn("— Select a network —".encode(), page)

    def test_active_profile_scope_preselects_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, client, _ = two_lab_world(Path(tmp))
            client.get("/?scope=lab-b")
            page = client.get("/discovery").data
            self.assertIn(b'data-profile-id="lab-b" selected', page)

    def test_refresh_reattaches_to_a_running_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            gate = GateOnHost(combined_network(), "10.0.0.1")
            _, _, client, manager = two_lab_world(workdir, transport_factory=gate)
            job_id = client.post(
                "/api/discovery/jobs", data={"profile": "Lab A"}
            ).get_json()["job"]["job_id"]
            self.assertTrue(
                poll_until(lambda: manager.get(job_id).status == "running")
            )
            # A page refresh renders the live job so polling can resume; the
            # run itself is untouched by the browser round-trip.
            page = client.get("/discovery").data
            self.assertIn(f'data-job-id="{job_id}"'.encode(), page)
            self.assertIn(b'data-status="running"', page)
            gate.gate.set()
            finished = manager.wait(job_id, timeout=30)
            self.assertEqual("completed", finished.status)

    def test_sync_fallback_route_runs_through_the_job_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, _, client, manager = two_lab_world(workdir)
            response = client.post(
                "/discovery/run", data={"profile": "Lab B"}, follow_redirects=True
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"finished successfully", response.data)
            jobs = client.get("/api/discovery/jobs").get_json()["jobs"]
            self.assertEqual(1, len(jobs))
            self.assertEqual("completed", jobs[0]["status"])
            self.assertEqual("Lab B", jobs[0]["profile_name"])


class JobManagerRestartTests(unittest.TestCase):
    def test_interrupted_jobs_are_marked_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist = Path(tmp) / "jobs.json"
            persist.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "job_id": "aaa111",
                                "profile_id": "lab-a",
                                "profile_name": "Lab A",
                                "management_ip": "10.0.0.1",
                                "status": "running",
                                "stage_number": 3,
                                "message": "Discovering neighbors",
                                "started_at": "2026-07-10T08:00:00+00:00",
                            },
                            {
                                "job_id": "bbb222",
                                "profile_id": "lab-b",
                                "profile_name": "Lab B",
                                "management_ip": "10.0.1.1",
                                "status": "completed",
                                "stage_number": 7,
                                "message": "Discovery completed successfully",
                                "summary": {"devices": 1},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manager = DiscoveryJobManager(
                runner=lambda *args: {},
                profile_service=None,
                persist_path=persist,
            )
            by_id = {job["job_id"]: job for job in manager.list_recent()}
            self.assertEqual("interrupted", by_id["aaa111"]["status"])
            self.assertIn("restarted", by_id["aaa111"]["error"])
            # Completed history survives the restart untouched.
            self.assertEqual("completed", by_id["bbb222"]["status"])
            self.assertEqual({"devices": 1}, by_id["bbb222"]["summary"])
            # The honest state is persisted back for the next restart too.
            saved = json.loads(persist.read_text(encoding="utf-8"))
            statuses = {entry["job_id"]: entry["status"] for entry in saved["jobs"]}
            self.assertEqual("interrupted", statuses["aaa111"])


if __name__ == "__main__":
    unittest.main()
