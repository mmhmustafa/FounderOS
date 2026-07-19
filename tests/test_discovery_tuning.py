"""Discovery tuning: system-suggested concurrency and connect timeout.

The wizard's "Concurrent sessions" and "Timeout seconds" were validated
but never reached the engine (which silently auto-sized its own worker
pool). The contract now: blank = auto — the system suggests, the preview
quotes the suggestion honestly — and an explicit value flows wizard →
plan → profile → runner/transport, bounded at every layer.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from founderos_atlas.discovery.entry import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DiscoveryPlanError,
    MAX_CONCURRENCY,
    resolve_plan,
    suggested_concurrency,
)
from founderos_atlas.workspace.exceptions import InvalidProfileError

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_unified_pipeline import full_outputs


class SuggestionTests(unittest.TestCase):
    def test_suggestion_scales_with_the_candidate_list(self) -> None:
        self.assertEqual(4, suggested_concurrency(1))
        self.assertEqual(4, suggested_concurrency(4))
        self.assertEqual(8, suggested_concurrency(8))
        self.assertEqual(MAX_CONCURRENCY, suggested_concurrency(254))
        self.assertEqual(MAX_CONCURRENCY, suggested_concurrency(10_000))

    def test_plan_auto_uses_the_suggestion_and_says_so(self) -> None:
        plan = resolve_plan(
            "management-network", cidr="192.0.2.0/28", policy="fast",
        )
        self.assertIsNone(plan.concurrency)
        self.assertIsNone(plan.timeout_seconds)
        self.assertEqual(
            suggested_concurrency(len(plan.candidates)),
            plan.effective_concurrency,
        )
        self.assertEqual(
            DEFAULT_CONNECT_TIMEOUT_SECONDS, plan.effective_timeout_seconds
        )
        payload = plan.to_dict()
        self.assertTrue(payload["concurrency_suggested"])
        self.assertTrue(payload["timeout_suggested"])

    def test_explicit_values_win_and_are_bounded(self) -> None:
        plan = resolve_plan(
            "management-network", cidr="192.0.2.0/28", policy="fast",
            concurrency=2, timeout_seconds=30,
        )
        self.assertEqual(2, plan.effective_concurrency)
        self.assertEqual(30, plan.effective_timeout_seconds)
        self.assertFalse(plan.to_dict()["concurrency_suggested"])
        with self.assertRaises(DiscoveryPlanError):
            resolve_plan(
                "management-network", cidr="192.0.2.0/28", policy="fast",
                concurrency=MAX_CONCURRENCY + 1,
            )
        with self.assertRaises(DiscoveryPlanError):
            resolve_plan(
                "management-network", cidr="192.0.2.0/28", policy="fast",
                timeout_seconds=0,
            )


class ProfileSchemaTests(unittest.TestCase):
    def _service(self, tmp: Path):
        from founderos_atlas.workspace import ProfileService
        from founderos_atlas.workspace.credentials import (
            InMemoryCredentialProvider,
        )
        from founderos_atlas.workspace.repository import ProfileRepository

        return ProfileService(
            ProfileRepository(tmp), InMemoryCredentialProvider()
        )

    def test_tuning_persists_and_none_means_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Path(tmp))
            service.add_profile(
                name="Lab", management_ip="10.0.0.1", username="u",
                password="pw", concurrency=8, connect_timeout_seconds=10,
            )
            stored = self._service(Path(tmp)).get_profile("Lab")
            self.assertEqual(8, stored.concurrency)
            self.assertEqual(10, stored.connect_timeout_seconds)
            # update: omitted keeps, explicit None resets to auto.
            service.update_profile("Lab", max_devices=20)
            kept = service.get_profile("Lab")
            self.assertEqual(8, kept.concurrency)
            service.update_profile(
                "Lab", concurrency=None, connect_timeout_seconds=None,
            )
            reset = service.get_profile("Lab")
            self.assertIsNone(reset.concurrency)
            self.assertIsNone(reset.connect_timeout_seconds)

    def test_bounds_are_enforced_on_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Path(tmp))
            with self.assertRaises(InvalidProfileError):
                service.add_profile(
                    name="Bad", management_ip="10.0.0.1", username="u",
                    password="pw", concurrency=33,
                )
            with self.assertRaises(InvalidProfileError):
                service.add_profile(
                    name="Bad2", management_ip="10.0.0.1", username="u",
                    password="pw", connect_timeout_seconds=61,
                )

    def test_resolved_inputs_carry_the_tuning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Path(tmp))
            service.add_profile(
                name="Lab", management_ip="10.0.0.1", username="u",
                password="pw", concurrency=6, connect_timeout_seconds=12,
            )
            inputs = service.resolve_discovery_inputs("Lab")
            self.assertEqual(6, inputs.concurrency)
            self.assertEqual(12, inputs.connect_timeout_seconds)


class WizardFlowTests(unittest.TestCase):
    def client(self, workdir: Path):
        from founderos_atlas.web import create_app
        from tests.test_profile_isolation import make_service

        service = make_service(workdir)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def _await_job(self, client) -> None:
        import time

        for _ in range(200):
            jobs = client.get("/api/discovery/jobs").get_json()["jobs"]
            if jobs and jobs[0]["status"] not in ("queued", "running"):
                return
            time.sleep(0.05)

    def test_preview_quotes_the_suggestion_when_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = self.client(Path(tmp))
            page = client.post("/discovery/wizard/preview", data={
                "mode": "management-network", "cidr": "10.20.20.0/28",
                "policy": "fast",
            }).data.decode("utf-8")
            self.assertIn("(suggested)", page)
            self.assertIn("Concurrency", page)
            self.assertIn("Timeout", page)

    def test_explicit_values_reach_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.client(workdir)
            network = ScriptedNetwork(
                {"10.0.0.1": full_outputs("R1", "10.0.0.1")}
            )
            client.application.config["ATLAS_TRANSPORT_FACTORY"] = (
                lambda credentials: network.transport_factory(
                    credentials.host
                )
            )
            response = client.post("/discovery/wizard/start", data={
                "mode": "seed", "seed": "10.0.0.1", "policy": "balanced",
                "name": "Tuned", "username": "atlas", "password": PASSWORD,
                "concurrency": "2", "timeout_seconds": "20",
            }, follow_redirects=True)
            self.assertIn(b"Discovery started", response.data)
            profile = service.get_profile("Tuned")
            self.assertEqual(2, profile.concurrency)
            self.assertEqual(20, profile.connect_timeout_seconds)
            self._await_job(client)

    def test_blank_fields_stay_auto_on_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.client(workdir)
            network = ScriptedNetwork(
                {"10.0.0.1": full_outputs("R1", "10.0.0.1")}
            )
            client.application.config["ATLAS_TRANSPORT_FACTORY"] = (
                lambda credentials: network.transport_factory(
                    credentials.host
                )
            )
            response = client.post("/discovery/wizard/start", data={
                "mode": "seed", "seed": "10.0.0.1", "policy": "balanced",
                "name": "Auto", "username": "atlas", "password": PASSWORD,
                "concurrency": "", "timeout_seconds": "",
            }, follow_redirects=True)
            self.assertIn(b"Discovery started", response.data)
            profile = service.get_profile("Auto")
            self.assertIsNone(profile.concurrency)
            self.assertIsNone(profile.connect_timeout_seconds)
            self._await_job(client)


class TransportTimeoutTests(unittest.TestCase):
    def test_transport_accepts_and_stores_the_override(self) -> None:
        from founderos_atlas.transport import (
            DeviceCredentials,
            SSHDeviceTransport,
        )

        transport = SSHDeviceTransport(
            DeviceCredentials(
                host="10.0.0.1", username="u", password="pw"
            ),
            connect_timeout=17.0,
        )
        self.assertEqual(17.0, transport._connect_timeout)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
