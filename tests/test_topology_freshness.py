"""Topology last-known-good freshness (PR-179 Step 4, §30.4).

Measured before this change: after a failed discovery, Topology kept
rendering yesterday's graph with no marker at all — Home said "as of",
Topology said nothing — so the most authoritative visual Atlas renders
could be mistaken for current (beta blocker B4).

The banner exists only while the LATEST terminal discovery attempt for
the visible scope failed, and it states BOTH the age of what is shown
and the consecutive failed attempts since ("as of <date>" alone
quietly ages into "silently ancient"). Everything is read from the job
manager's in-memory record and the snapshot timestamp already loaded —
no extra store scan. The stale graph itself keeps rendering: last
known good is preserved, only its presentation gains the truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.transport.exceptions import AuthenticationError

from tests.test_multihop_discovery import ScriptedNetwork, device_outputs
from tests.test_web_app import add_profile, build_client, make_service


BANNER = 'data-degraded="topology-freshness"'


def flat(body: bytes) -> str:
    return " ".join(body.decode("utf-8").split())


class TopologyFreshnessTests(unittest.TestCase):
    def _client(self, workdir: Path):
        """A client whose transport can be flipped between a working
        two-device network and refused credentials."""

        service = make_service(workdir)
        add_profile(service, management_ip="10.0.0.1")
        network = ScriptedNetwork({
            "10.0.0.1": device_outputs(
                "R1", "10.0.0.1", (("SW1", "10.0.0.2"),)
            ),
            "10.0.0.2": device_outputs(
                "SW1", "10.0.0.2", (("R1", "10.0.0.1"),)
            ),
        })
        mode = {"fail": False}

        def factory(connection):
            if mode["fail"]:
                raise AuthenticationError(
                    f"Authentication failed for {connection.host}."
                )
            return network.transport_factory(connection.host)

        base = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
        ticks = count()
        _, client = build_client(
            workdir, service, transport_factory=factory,
            clock=lambda: base + timedelta(seconds=next(ticks)),
        )
        profile_id = service.get_profile("Hyderabad Lab").profile_id
        return client, mode, profile_id

    def _run_discovery(self, client) -> bytes:
        response = client.post(
            "/discovery/run", data={"profile": "Hyderabad Lab"},
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        return response.data

    def test_last_known_good_carries_age_and_failed_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, mode, profile_id = self._client(Path(tmp))
            self.assertIn(b"finished successfully",
                          self._run_discovery(client))

            # Healthy: the graph is current, so there is no banner.
            body = client.get(f"/topology?scope={profile_id}").data
            self.assertNotIn(BANNER.encode(), body)

            # The estate stops answering our credentials; the run fails
            # but the last good snapshot is preserved (pinned earlier).
            mode["fail"] = True
            self._run_discovery(client)

            response = client.get(f"/topology?scope={profile_id}")
            self.assertEqual(200, response.status_code)
            body = flat(response.data)
            self.assertIn(BANNER, body)
            self.assertIn("Showing the last successful topology", body)
            self.assertIn("The latest discovery attempt", body)
            self.assertIn("failed", body)
            self.assertIn(
                "1 attempt(s) have failed since this topology was collected",
                body,
            )
            # The graph itself still renders — the banner qualifies it,
            # never replaces it.
            self.assertIn("topology-frame", body)

            # A second failed attempt raises the count — the banner can
            # never quietly age.
            self._run_discovery(client)
            body = flat(client.get(f"/topology?scope={profile_id}").data)
            self.assertIn(
                "2 attempt(s) have failed since this topology was collected",
                body,
            )

    def test_enterprise_view_states_the_same_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, mode, _profile_id = self._client(Path(tmp))
            self._run_discovery(client)
            self.assertNotIn(BANNER.encode(), client.get("/topology").data)
            mode["fail"] = True
            self._run_discovery(client)
            body = flat(client.get("/topology").data)
            self.assertIn(BANNER, body)
            self.assertIn("Showing the last successful topology", body)
            # The enterprise banner names WHICH network's attempt failed.
            self.assertIn("for Hyderabad Lab", body)

    def test_a_later_success_clears_the_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, mode, profile_id = self._client(Path(tmp))
            self._run_discovery(client)
            mode["fail"] = True
            self._run_discovery(client)
            self.assertIn(
                BANNER.encode(),
                client.get(f"/topology?scope={profile_id}").data,
            )
            mode["fail"] = False
            self.assertIn(b"finished successfully",
                          self._run_discovery(client))
            self.assertNotIn(
                BANNER.encode(),
                client.get(f"/topology?scope={profile_id}").data,
            )

    def test_a_failure_in_one_network_never_marks_another(self) -> None:
        # Scope isolation: the banner is derived from the VISIBLE
        # scope's own job history.
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client, mode, profile_id = self._client(workdir)
            self._run_discovery(client)
            mode["fail"] = True
            self._run_discovery(client)
            from founderos_atlas.web.jobs import DiscoveryJobManager  # noqa: F401

            # A different profile with no failures: its scoped view
            # must stay unmarked even while Hyderabad's latest failed.
            body = client.get(f"/topology?scope={profile_id}").data
            self.assertIn(BANNER.encode(), body)
            other = client.get("/topology?scope=default").data
            self.assertNotIn(BANNER.encode(), other)


if __name__ == "__main__":
    unittest.main()
