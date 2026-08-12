"""Progressive first-run navigation (PR-177).

Before a workspace holds a usable discovery, the sidebar shows three
doors — Overview, Discover, Settings — and the rest of Atlas appears
with the first evidence. These tests pin the three load-bearing
properties: the unlock signal is authoritative and cheap (a failed run
never reveals; a partial run does; the answer survives restarts and
profile deletion via the durable marker); the filter is GUIDANCE, not
access control (every route stays reachable, Ctrl+K stays unnarrowed,
RBAC is untouched); and the two sidebar render sites cannot disagree.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from founderos_atlas.web.models import (
    NAV_GROUPS,
    NavGroup,
    NavItem,
    PRE_DISCOVERY_ITEM_KEYS,
    guided_nav_groups,
)

from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in
from tests.test_profile_isolation import FIXED, add_profile, run_discover


ALL_HREFS = tuple(
    item.href for group in NAV_GROUPS for item in group.items
)


def _sidebar(page: str) -> str:
    """The rendered sidebar's markup (the nav element only)."""

    return page.split('<nav class="sidebar"')[1].split("</nav>")[0]


def _sidebar_hrefs(page: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', _sidebar(page))


def _dead_network() -> ScriptedNetwork:
    """Nothing answers: the total-failure discovery."""

    return ScriptedNetwork({})


# -- 1. The pure filter (no Flask) --------------------------------------------


class GuidedFilterTests(unittest.TestCase):
    GROUPS = (
        NavGroup("home", "Home", "/", (
            NavItem("dashboard", "Overview", "/"),
            NavItem("inbox", "Action Center", "/inbox"),
        )),
        NavGroup("network", "Network", "/topology", (
            NavItem("topology", "Topology", "/topology"),
        )),
        NavGroup("administration", "Administration", "/discovery", (
            NavItem("discovery", "Discover", "/discovery"),
            NavItem("settings", "Settings", "/settings"),
            NavItem("hidden-tool", "Hidden Tool", "/tool", sidebar=False),
        )),
    )

    def test_before_reveal_only_the_allowlist_survives(self) -> None:
        groups = guided_nav_groups(self.GROUPS, revealed=False)
        keys = [item.key for group in groups for item in group.items]
        self.assertEqual(["dashboard", "discovery", "settings"], keys)
        # The emptied Network group is gone entirely.
        self.assertEqual(["home", "administration"], [g.key for g in groups])

    def test_after_reveal_everything_but_non_sidebar_items(self) -> None:
        groups = guided_nav_groups(self.GROUPS, revealed=True)
        keys = [item.key for group in groups for item in group.items]
        self.assertIn("topology", keys)
        self.assertIn("inbox", keys)
        self.assertNotIn("hidden-tool", keys)      # sidebar=False always drops

    def test_the_filter_is_pure(self) -> None:
        before = tuple(self.GROUPS)
        guided_nav_groups(self.GROUPS, revealed=False)
        self.assertEqual(before, self.GROUPS)      # untouched input

    def test_the_allowlist_names_real_frozen_keys(self) -> None:
        keys = {item.key for group in NAV_GROUPS for item in group.items}
        self.assertTrue(PRE_DISCOVERY_ITEM_KEYS <= keys)


# -- 2. The readiness signal case table ---------------------------------------


class ReadinessSignalTests(unittest.TestCase):
    def _app(self, tmp: Path):
        from founderos_atlas.web import create_app

        app = create_app(
            output_dir=tmp,
            history_root=tmp / ".atlas" / "history",
            workspace_root=tmp / "workspace",
        )
        app.config.update(TESTING=True)
        return app

    def _revealed(self, app) -> bool:
        from founderos_atlas.web.models import workspace_has_discovery

        with app.test_request_context("/"):
            return workspace_has_discovery(app)

    def test_fresh_workspace_is_not_revealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(self._revealed(self._app(Path(tmp))))

    def test_a_topology_snapshot_alone_reveals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "topology_snapshot.json").write_text("{}")
            self.assertTrue(self._revealed(self._app(Path(tmp))))

    def test_a_history_directory_alone_reveals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / ".atlas" / "history" / "2026-08-12_10-00-00"
            record.mkdir(parents=True)
            self.assertTrue(self._revealed(self._app(Path(tmp))))

    def test_the_marker_alone_reveals_and_survives_restart(self) -> None:
        # The profile-deleted-after-discovery case: scope data exists but
        # no profile names it; the marker written at reveal time keeps
        # the workspace operational across a restart.
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".atlas" / "nav-revealed"
            marker.parent.mkdir(parents=True)
            marker.touch()
            self.assertTrue(self._revealed(self._app(Path(tmp))))

    def test_a_computed_reveal_writes_the_durable_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "topology_snapshot.json").write_text("{}")
            app = self._app(Path(tmp))
            self.assertTrue(self._revealed(app))
            self.assertTrue((Path(tmp) / ".atlas" / "nav-revealed").is_file())

    def test_the_latch_survives_evidence_deletion_within_a_process(self) -> None:
        # A nav that re-hides itself mid-session is worse than one that
        # outlives its data by one process lifetime (approved semantics).
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "topology_snapshot.json"
            snapshot.write_text("{}")
            app = self._app(Path(tmp))
            self.assertTrue(self._revealed(app))
            snapshot.unlink()
            (Path(tmp) / ".atlas" / "nav-revealed").unlink()
            self.assertTrue(self._revealed(app))   # the latch holds

    def test_restore_onto_a_clean_machine_returns_to_setup(self) -> None:
        # The backup manifest carries the WORKSPACE (profiles.json), not
        # the output directory — so a restored profile with a
        # last_discovery stamp but no data must NOT reveal.
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            add_profile(
                app.config["ATLAS_PROFILE_SERVICE"], "Restored", "10.0.0.1"
            )
            self.assertFalse(self._revealed(app))

    def test_a_failed_discovery_does_not_reveal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir, discover=False)
            try:
                run_discover(workdir, service, _dead_network(),
                             "Hyderabad", FIXED)
            except Exception:  # noqa: BLE001 - the failure IS the fixture
                pass
            page = client.get("/").get_data(as_text=True)
            self.assertEqual(
                {"/", "/discovery", "/settings"}, set(_sidebar_hrefs(page)),
                "a failed run must leave first-run guidance in place",
            )

    def test_a_successful_discovery_reveals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = build_world(Path(tmp))    # discovers twice
            hrefs = _sidebar_hrefs(client.get("/").get_data(as_text=True))
            self.assertIn("/topology", hrefs)
            self.assertIn("/policy", hrefs)
            self.assertGreater(len(hrefs), 20)

    def test_an_old_success_survives_a_new_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)       # both succeed
            try:
                run_discover(workdir, service, _dead_network(),
                             "Hyderabad", FIXED + timedelta(hours=3))
            except Exception:  # noqa: BLE001
                pass
            hrefs = _sidebar_hrefs(client.get("/").get_data(as_text=True))
            self.assertIn("/topology", hrefs, "a failure deletes nothing")


# -- 3. The rendered first-run experience -------------------------------------


class FirstRunSidebarTests(unittest.TestCase):
    def test_fresh_workspace_shows_exactly_three_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/").get_data(as_text=True)
            self.assertEqual(
                {"/", "/discovery", "/settings"}, set(_sidebar_hrefs(page))
            )

    def test_both_remaining_groups_are_open(self) -> None:
        # base.html regression guard: without the accordion fix a fresh
        # workspace rendered Home expanded and Administration COLLAPSED —
        # one visible link, not three doors.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            sidebar = _sidebar(client.get("/").get_data(as_text=True))
            details = re.findall(r'<details class="nav-details"\s*(open)?', sidebar)
            self.assertEqual(2, len(details))
            self.assertTrue(all(details), "both SETUP groups must be open")

    def test_the_sidebar_explains_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            self.assertIn(
                "More appears after your first discovery.",
                _sidebar(client.get("/").get_data(as_text=True)),
            )

    def test_a_deep_link_to_a_hidden_page_keeps_both_groups_open(self) -> None:
        # nav_group_for("topology") names a group that is not in the
        # filtered DOM; without the fix NOTHING opened and the sidebar
        # looked broken.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            sidebar = _sidebar(client.get("/topology").get_data(as_text=True))
            details = re.findall(r'<details class="nav-details"\s*(open)?', sidebar)
            self.assertEqual(2, len(details))
            self.assertTrue(all(details))

    def test_no_unread_badge_on_a_group_without_its_inbox(self) -> None:
        # Pre-reveal the Home group holds only Overview; a count that
        # points at a removed destination must not render.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            self.assertNotIn(
                "nav-count", _sidebar(client.get("/").get_data(as_text=True))
            )

    def test_two_render_sites_agree(self) -> None:
        # /users, /inbox and /system/integrity reach the sidebar ONLY
        # through the app-wide context processor; every other page goes
        # through base_context. Atlas has already shipped one bug where
        # two nav builders disagreed — this is the tripwire.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            reference = set(_sidebar_hrefs(client.get("/").get_data(as_text=True)))
            for path in ("/users", "/inbox", "/system/integrity"):
                page = client.get(path).get_data(as_text=True)
                self.assertEqual(
                    reference, set(_sidebar_hrefs(page)),
                    f"{path} rendered a different sidebar",
                )

    def test_the_topbar_shortcut_waits_for_the_reveal(self) -> None:
        # Pre-reveal, Home's "Run your first discovery" is THE primary;
        # the topbar Run Discovery shortcut returns with the workspace.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            self.assertNotIn(
                'class="run-form"', client.get("/").get_data(as_text=True)
            )
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            self.assertIn(
                'class="run-form"', client.get("/").get_data(as_text=True)
            )


# -- 4. Guidance, never access control ----------------------------------------


class GuidanceNotAccessControlTests(unittest.TestCase):
    def test_every_destination_stays_directly_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            for href in ALL_HREFS:
                response = client.get(href, follow_redirects=True)
                self.assertEqual(200, response.status_code, href)

    def test_a_hidden_deep_link_keeps_its_breadcrumb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/topology").get_data(as_text=True)
            crumbs = page.split('aria-label="Breadcrumb"')[1].split("</nav>")[0]
            self.assertIn("Network", crumbs)
            self.assertIn("Topology", crumbs)
            self.assertIn('aria-current="page"', crumbs)

    def test_ctrl_k_still_finds_hidden_pages_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            payload = client.get("/api/search?q=policy").get_json()
            groups = {group["id"]: group for group in payload["groups"]}
            self.assertIn("pages", groups)
            titles = [row["title"] for row in groups["pages"]["results"]]
            self.assertIn("Policy", titles)

    def test_a_viewer_is_never_guided_into_a_dead_end(self) -> None:
        # Only two of seven roles hold discovery.run. A viewer on a
        # fresh workspace could do NOTHING to leave SETUP, so guidance
        # does not apply to them: they get the full RBAC-filtered nav.
        with production_world() as (app, _):
            viewer, _csrf = sign_in(app, "viewer")
            page = viewer.get("/").get_data(as_text=True)
            hrefs = _sidebar_hrefs(page)
            self.assertIn("/topology", hrefs)       # not the 3-door SETUP nav
            self.assertNotIn("/users", hrefs)       # RBAC still filters
            # An operator who CAN discover is guided on the same workspace.
            operator, _csrf = sign_in(app, "operator")
            op_hrefs = _sidebar_hrefs(operator.get("/").get_data(as_text=True))
            self.assertEqual({"/", "/discovery", "/settings"}, set(op_hrefs))


# -- 5. PRISM Playground placement ---------------------------------------------


class PlaygroundPlacementTests(unittest.TestCase):
    def test_absent_from_the_sidebar_present_everywhere_else(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))       # revealed workspace
            page = client.get("/").get_data(as_text=True)
            self.assertNotIn("/prism/playground", _sidebar(page))
            # Directly reachable…
            self.assertEqual(
                200, client.get("/prism/playground").status_code
            )
            # …with its breadcrumb and page model intact…
            playground = client.get("/prism/playground").get_data(as_text=True)
            self.assertIn('aria-current="page"', playground)
            from founderos_atlas.web import workspace as ws

            self.assertIn(
                "PRISM Playground", [p["label"] for p in ws.pages()]
            )
            # …and with a front door under Settings → PRISM.
            settings = client.get("/settings/ai").get_data(as_text=True)
            self.assertIn('href="/prism/playground"', settings)
            self.assertIn("Try PRISM on sample evidence", settings)


# -- 6. Discovery-page hierarchy -----------------------------------------------


class DiscoveryHierarchyTests(unittest.TestCase):
    def test_no_profile_state_leads_with_add_profile(self) -> None:
        # build_world always creates two profiles, so build a truly
        # profile-less app. The hidden job panel's completion actions
        # are excluded: they render only after a run, never compete on
        # first paint.
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_dir=Path(tmp),
                history_root=Path(tmp) / ".atlas" / "history",
                workspace_root=Path(tmp) / "workspace",
            )
            app.config.update(TESTING=True)
            page = app.test_client().get("/discovery").get_data(as_text=True)
            visible = page.split("<main")[1].split('id="job-panel"')[0]
            primaries = re.findall(
                r'<a class="btn btn-primary"[^>]*href="([^"]+)"', visible
            )
            self.assertEqual(["/profiles/new"], primaries,
                             "Add discovery profile must be the one primary")
            self.assertIn("Add discovery profile", visible)
            self.assertIn("where to connect and how", visible)
            self.assertIn('href="/discovery/wizard"', visible)  # guided alternative
            self.assertNotIn("Execution Console", visible)
            self.assertNotIn("(sample)", visible)

    def test_profile_ready_state_leads_with_run_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/discovery").get_data(as_text=True)
            main = page.split("<main")[1]
            # The form submit is the one primary; the wizard is secondary.
            # (The hidden job panel's completion actions render only
            # after a run, so they are excluded from the first paint.)
            visible = main.split('id="job-panel"')[0]
            self.assertIn('id="discovery-run"', main)
            anchor_primaries = re.findall(
                r'<a class="btn btn-primary"[^>]*>([^<]+)</a>', visible
            )
            self.assertEqual([], anchor_primaries,
                             "no anchor competes with the Run Discovery submit")
            self.assertNotIn("Execution Console", main)

    def test_the_profiles_run_button_parameter_is_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get(
                "/discovery?profile=Secunderabad"
            ).get_data(as_text=True)
            self.assertIn("Secunderabad", page.split("<main")[1])
            match = re.search(
                r'<option value="Secunderabad"[^>]*selected', page
            )
            self.assertIsNotNone(match, "?profile= must preselect the network")

    def test_first_profile_creation_lands_on_discover(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_dir=Path(tmp),
                history_root=Path(tmp) / ".atlas" / "history",
                workspace_root=Path(tmp) / "workspace",
            )
            app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
            client = app.test_client()
            page = client.get("/profiles/new").get_data(as_text=True)
            token = re.search(
                r'name="csrf_token"[^>]*value="([^"]+)"', page
            )
            data = {
                "name": "First Lab", "management_ip": "10.0.0.1",
                "username": "ops", "password": "pw",
            }
            if token:
                data["csrf_token"] = token.group(1)
            response = client.post("/profiles", data=data)
            self.assertEqual(302, response.status_code)
            self.assertIn("/discovery", response.headers["Location"])
            self.assertIn("scope=", response.headers["Location"])

    def test_later_profile_creation_returns_to_the_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = build_world(Path(tmp))    # revealed
            page = client.get("/profiles/new").get_data(as_text=True)
            token = re.search(
                r'name="csrf_token"[^>]*value="([^"]+)"', page
            )
            data = {
                "name": "Third Lab", "management_ip": "10.7.7.7",
                "username": "ops", "password": "pw",
            }
            if token:
                data["csrf_token"] = token.group(1)
            response = client.post("/profiles", data=data)
            self.assertEqual(302, response.status_code)
            self.assertTrue(
                response.headers["Location"].endswith("/profiles"),
                response.headers["Location"],
            )


# -- 7. First-run Home framing ---------------------------------------------------


class FirstRunHomeTests(unittest.TestCase):
    def test_home_frames_the_product_and_leads_to_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/").get_data(as_text=True)
            main = page.split("<main")[1]
            self.assertIn(
                "Atlas explains your network from evidence it collects", main
            )
            self.assertIn("read-only", main)
            self.assertIn("btn-first-discovery", main)
            self.assertIn("Run your first discovery", main)

    def test_pre_discovery_noise_is_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            main = client.get("/").get_data(as_text=True).split("<main")[1]
            self.assertNotIn("Continue Working", main)
            self.assertNotIn("All workflows", main)
            self.assertNotIn("Investigate an Issue", main)

    def test_populated_home_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            main = client.get("/").get_data(as_text=True).split("<main")[1]
            self.assertIn("Continue Working", main)
            self.assertNotIn("btn-first-discovery", main)


if __name__ == "__main__":
    unittest.main()
