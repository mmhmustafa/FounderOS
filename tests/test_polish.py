"""Acceptance tests for PR-041 — Product Readiness (POLISH).

No new engines: enterprise-first language, navigation without dead
ends, teaching empty states, device-aware form filtering everywhere,
accessibility affordances, and the enterprise-graph request cache.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from tests.test_atlas_transport import PASSWORD
from tests.test_federation import hyderabad_network, secunderabad_network
from tests.test_profile_isolation import FIXED, add_profile, make_service, run_discover


def build_world(workdir: Path, *, discover: bool = True):
    from founderos_atlas.web import create_app

    service = make_service(workdir)
    add_profile(service, "Hyderabad", "10.0.0.1")
    add_profile(service, "Secunderabad", "10.0.1.1")
    if discover:
        run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
        run_discover(
            workdir, service, secunderabad_network(), "Secunderabad",
            FIXED + timedelta(minutes=30),
        )
    app = create_app(
        profile_service=service,
        output_dir=workdir,
        history_root=workdir / ".atlas" / "history",
        workspace_root=workdir / "workspace",
    )
    app.config.update(TESTING=True)
    return service, app.test_client()


class EnterpriseFirstLanguageTests(unittest.TestCase):
    def test_global_scope_is_labelled_enterprise(self) -> None:
        from founderos_atlas.workspace import GLOBAL_SCOPE_ID, GLOBAL_SCOPE_LABEL

        self.assertEqual("Enterprise", GLOBAL_SCOPE_LABEL)
        self.assertEqual("all", GLOBAL_SCOPE_ID)  # URLs/sessions stay stable

    def test_selector_and_titles_use_enterprise_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/?scope=all").data
            self.assertIn(b"Mission \xe2\x80\x94 Enterprise", page)
            self.assertIn(b'<option value="all" selected>Enterprise</option>', page)
            self.assertIn(b"Scope", page)
            self.assertNotIn(b"All Networks", page)
            topology = client.get("/topology?scope=all").data
            self.assertIn(b"Topology \xe2\x80\x94 Enterprise", topology)
            self.assertNotIn(b"All Networks", topology)

    def test_search_labels_enterprise_scope_reports_as_enterprise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            client.get("/paths?scope=all")
            client.post(
                "/paths/run",
                data={"source": "A1", "destination": "B1"},
                follow_redirects=True,
            )
            payload = client.get("/api/search?q=investigation").get_json()
            group = next(
                g for g in payload["groups"] if g["id"] == "investigations"
            )
            self.assertIn("Enterprise", group["results"][0]["subtitle"])


class NavigationTests(unittest.TestCase):
    def test_detail_pages_offer_back_navigation(self) -> None:
        from founderos_atlas.compass import PlanRepository, create_plan

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            payload = client.get("/api/search?q=GW").get_json()
            href = next(
                g for g in payload["groups"] if g["id"] == "devices"
            )["results"][0]["href"]
            device_page = client.get(href).data
            self.assertIn(b"back-link", device_page)
            self.assertIn(b"Enterprise inventory", device_page)
            create_plan(
                PlanRepository(workdir), title="Window", maintenance_window="Sat",
                engineer="netops", created_at="2026-07-12T08:00:00+00:00",
            )
            plan_page = client.get("/compass/window").data
            self.assertIn(b"back-link", plan_page)
            self.assertIn(b"All maintenance plans", plan_page)

    def test_incidents_enterprise_scope_is_not_a_dead_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/incidents?scope=all").data
            # PR-047A: the cross-link names the destination as the navigation
            # names it (Analyze > Investigate).
            self.assertIn(b"Investigate", page)
            self.assertIn(b"What is an incident investigation?", page)
            self.assertIn(b"Investigate a path instead", page)


class EmptyStateTests(unittest.TestCase):
    def test_empty_pages_teach_and_offer_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            history = client.get("/history?scope=all").data
            self.assertIn(b"What is discovery history?", history)
            self.assertIn(b"Run a discovery", history)
            changes = client.get("/changes?scope=all").data
            self.assertIn(b"What is change intelligence?", changes)
            self.assertIn(b"what changed overnight", changes)
            incidents = client.get("/incidents?scope=all").data
            self.assertIn(b"What is an incident investigation?", incidents)


class FormTests(unittest.TestCase):
    def test_compass_interfaces_are_device_aware(self) -> None:
        from founderos_atlas.compass import PlanRepository, create_plan

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            create_plan(
                PlanRepository(workdir), title="Window", maintenance_window="Sat",
                engineer="netops", created_at="2026-07-12T08:00:00+00:00",
            )
            page = client.get("/compass/window").data.decode("utf-8")
            self.assertIn('id="compass-device"', page)
            self.assertIn('id="compass-interface"', page)
            self.assertIn('data-device="GW"', page)
            self.assertIn('data-keep="1"', page)  # the "none" option survives
            script = client.get("/static/atlas.js").data.decode("utf-8")
            self.assertIn("bindInterfaceFilter", script)
            self.assertIn('"compass-device", "compass-interface"', script)
            # Predict keeps its existing filtering through the same code.
            self.assertIn('"predict-device", "predict-interface"', script)


class AccessibilityTests(unittest.TestCase):
    def test_focus_skip_link_and_aria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertIn('class="skip-link"', page)
            self.assertIn('id="atlas-main"', page)
            self.assertIn('aria-current="page"', page)
            self.assertIn('aria-live="polite"', page)
            css = client.get("/static/atlas.css").data.decode("utf-8")
            self.assertIn(":focus-visible", css)
            self.assertIn(".skip-link:focus", css)


class PerformanceTests(unittest.TestCase):
    def test_enterprise_graph_is_cached_until_evidence_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)
            client.get("/topology?scope=all")
            snapshot = workdir / ".atlas" / "enterprise" / "topology_snapshot.json"
            first_stat = (snapshot.stat().st_mtime_ns, snapshot.stat().st_size)
            # Repeat enterprise pages: same evidence, no artifact rewrite.
            client.get("/?scope=all")
            client.get("/topology?scope=all")
            client.get("/predict?scope=all")
            self.assertEqual(
                first_stat,
                (snapshot.stat().st_mtime_ns, snapshot.stat().st_size),
            )
            # New evidence (a re-discovery) invalidates the cache.
            run_discover(
                workdir, service, hyderabad_network(), "Hyderabad",
                FIXED + timedelta(hours=2),
            )
            client.get("/topology?scope=all")
            self.assertNotEqual(
                first_stat[0], snapshot.stat().st_mtime_ns
            )

    def test_cached_pages_still_have_no_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            client.get("/?scope=all")
            page = client.get("/?scope=all").data
            self.assertNotIn(PASSWORD.encode(), page)


if __name__ == "__main__":
    unittest.main()
