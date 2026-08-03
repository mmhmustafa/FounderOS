"""PR-170 — the Atlas workspace.

The claim under test: an operator always knows where they are, what is
related, and how to get back — built from data Atlas already has, with
no new source of truth and no invented destination.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from founderos_atlas.web import workspace as ws


class BreadcrumbTests(unittest.TestCase):
    """Part 1: every page exposes its location."""

    def test_a_page_gets_its_trail_from_the_nav_registry(self) -> None:
        crumbs = ws.breadcrumbs("advisor")
        self.assertEqual([c["label"] for c in crumbs],
                         ["Home", "Analyze", "Advisor"])

    def test_home_does_not_repeat_itself(self) -> None:
        crumbs = ws.breadcrumbs("dashboard")
        self.assertEqual([c["label"] for c in crumbs], ["Home", "Overview"])

    def test_the_current_page_is_not_a_link_to_itself(self) -> None:
        crumbs = ws.breadcrumbs("advisor")
        self.assertEqual(crumbs[-1]["href"], "")
        self.assertTrue(all(c["href"] for c in crumbs[:-1]))

    def test_a_page_can_append_what_only_it_knows(self) -> None:
        crumbs = ws.breadcrumbs("advisor", trail=[
            {"label": "Investigation", "href": "/advisor?conversation=0"},
            {"label": "BGP"},
        ])
        self.assertEqual([c["label"] for c in crumbs],
                         ["Home", "Analyze", "Advisor", "Investigation",
                          "BGP"])
        self.assertEqual(crumbs[-1]["href"], "")

    def test_every_crumb_carries_the_active_scope(self) -> None:
        """A trail that drops the scope walks the operator back into a
        different estate than the one they were looking at."""

        crumbs = ws.breadcrumbs("advisor", scope_id="hyderabad")
        for crumb in crumbs[:-1]:
            self.assertIn("scope=hyderabad", crumb["href"])

    def test_an_unknown_page_still_gets_a_way_home(self) -> None:
        crumbs = ws.breadcrumbs("not-a-real-page")
        self.assertEqual([c["label"] for c in crumbs], ["Home"])

    def test_a_malformed_trail_entry_is_dropped_not_rendered(self) -> None:
        crumbs = ws.breadcrumbs("advisor", trail=[
            "not a mapping", {"href": "/x"}, {"label": "Real"},
        ])
        self.assertEqual(crumbs[-1]["label"], "Real")
        self.assertEqual(len(crumbs), 4)


class ScopeCarryingTests(unittest.TestCase):
    """Part 7: navigation understands context."""

    def test_the_scope_is_added_when_absent(self) -> None:
        self.assertEqual(ws.with_scope("/topology", "hyderabad"),
                         "/topology?scope=hyderabad")

    def test_an_explicit_scope_always_wins(self) -> None:
        """A link that already names a scope was a deliberate choice."""

        self.assertEqual(ws.with_scope("/topology?scope=all", "hyderabad"),
                         "/topology?scope=all")

    def test_other_query_parameters_survive(self) -> None:
        result = ws.with_scope("/topology?focus=core1", "hyderabad")
        self.assertIn("focus=core1", result)
        self.assertIn("scope=hyderabad", result)

    def test_a_fragment_survives(self) -> None:
        self.assertIn("#inventory", ws.with_scope("/topology#inventory", "all"))

    def test_an_external_link_is_never_rewritten(self) -> None:
        self.assertEqual(ws.with_scope("https://example.net/x", "all"),
                         "https://example.net/x")

    def test_no_scope_means_no_change(self) -> None:
        self.assertEqual(ws.with_scope("/topology", ""), "/topology")


class RelatedObjectTests(unittest.TestCase):
    """Part 3: what else in Atlas holds this object."""

    def test_a_device_links_to_every_surface_that_holds_it(self) -> None:
        rows = ws.related("device", scope_id="all", device_id="ent:gw")
        labels = [row["label"] for row in rows]
        for expected in ("Topology", "Configuration", "Timeline",
                         "Evidence", "Policy", "Incidents"):
            self.assertIn(expected, labels)

    def test_every_related_link_explains_itself(self) -> None:
        for row in ws.related("device", scope_id="all"):
            self.assertTrue(row["why"], f"{row['label']} offers no reason")

    def test_related_links_carry_the_scope(self) -> None:
        for row in ws.related("device", scope_id="hyderabad"):
            self.assertIn("scope=hyderabad", row["href"])

    def test_a_device_link_focuses_the_topology_on_it(self) -> None:
        rows = {r["key"]: r for r in ws.related(
            "device", scope_id="all", device_id="ent:gw")}
        self.assertIn("focus=ent%3Agw", rows["topology"]["href"])

    def test_an_unknown_kind_offers_nothing(self) -> None:
        """Better an absent panel than one that invents destinations."""

        self.assertEqual(ws.related("sandwich"), [])


class ContextPanelTests(unittest.TestCase):
    """Part 2: never lose context while navigating."""

    def test_only_what_is_set_is_shown(self) -> None:
        items = ws.context_items(device="core1", protocol="BGP")
        self.assertEqual([i["label"] for i in items], ["Device", "Protocol"])

    def test_the_order_is_fixed_regardless_of_call_order(self) -> None:
        items = ws.context_items(protocol="BGP", site="mumbai",
                                 investigation="BGP between two endpoints")
        self.assertEqual([i["key"] for i in items],
                         ["investigation", "site", "protocol"])

    def test_empty_values_never_pad_the_strip(self) -> None:
        self.assertEqual(ws.context_items(device="", site=None), [])


class RecentsAndFavouritesTests(unittest.TestCase):
    """Parts 4 and 5."""

    def test_a_place_moves_to_the_front_rather_than_repeating(self) -> None:
        first = ws.remember([], kind="device", label="gw", href="/devices/gw")
        second = ws.remember(first, kind="device", label="sw",
                             href="/devices/sw")
        again = ws.remember(second, kind="device", label="gw",
                            href="/devices/gw")
        self.assertEqual([item["label"] for item in again], ["gw", "sw"])

    def test_recents_are_bounded(self) -> None:
        rows: list = []
        for index in range(40):
            rows = ws.remember(rows, kind="device", label=f"d{index}",
                               href=f"/devices/{index}")
        self.assertEqual(len(rows), ws.MAX_RECENTS)

    def test_pinning_is_a_toggle(self) -> None:
        pinned, added = ws.toggle_favourite(
            [], kind="page", label="Advisor", href="/advisor")
        self.assertTrue(added)
        self.assertTrue(ws.is_favourite(pinned, "/advisor"))
        unpinned, added_again = ws.toggle_favourite(
            pinned, kind="page", label="Advisor", href="/advisor")
        self.assertFalse(added_again)
        self.assertEqual(unpinned, [])

    def test_an_entry_without_a_destination_is_refused(self) -> None:
        self.assertEqual(ws.remember([], kind="page", label="X", href=""), [])
        self.assertEqual(ws.remember([], kind="page", label="", href="/x"), [])

    def test_a_full_list_still_fits_the_stores_size_limit(self) -> None:
        """The preference store refuses a value over 4 KB. The caps
        exist to stay under it — if they are ever raised, this fails
        before an operator discovers it by losing a pin."""

        import json

        from founderos_atlas.workspace.user_preferences import (
            UserPreferenceStore,
        )

        rows: list = []
        for index in range(ws.MAX_FAVOURITES):
            rows, _ = ws.toggle_favourite(
                rows, kind="device",
                # A realistically long label and href.
                label=f"chennai-regional-core-{index:02d}.example.net",
                href=f"/devices/ent:chennai-regional-core-{index:02d}"
                     f":10.106.20.{index}",
            )
        self.assertEqual(len(rows), ws.MAX_FAVOURITES)
        size = len(json.dumps(rows).encode("utf-8"))
        self.assertLess(size, UserPreferenceStore.MAX_UI_VALUE_BYTES,
                        f"favourites serialise to {size} bytes")

    def test_a_corrupt_stored_list_degrades_rather_than_raising(self) -> None:
        """The store is per-user JSON an older version may have written
        differently; a bad entry must drop out, not break the page."""

        for junk in ("not a list", [1, 2, 3], [{"label": "x"}], None,
                     [{"kind": "page", "label": "ok", "href": "/ok"}, "bad"]):
            with self.subTest(junk=junk):
                rows = ws._clean(junk, ws.MAX_RECENTS)
                self.assertIsInstance(rows, list)
                for row in rows:
                    self.assertTrue(row["label"] and row["href"])


class PaletteTests(unittest.TestCase):
    """Part 6: navigation without menus."""

    def test_every_page_is_reachable_from_the_palette(self) -> None:
        from founderos_atlas.web.models import NAV_GROUPS

        labels = {row["label"] for row in ws.palette_index()
                  if row["kind"] == "page"}
        for group in NAV_GROUPS:
            for item in group.items:
                self.assertIn(item.label, labels)

    def test_commands_are_destinations_not_actions(self) -> None:
        """A palette that mutates on Enter is a way to run discovery by
        accident. Every row is a link."""

        for row in ws.palette_index():
            self.assertTrue(row["href"].startswith("/"))

    def test_palette_links_carry_the_scope(self) -> None:
        for row in ws.palette_index("hyderabad"):
            self.assertIn("scope=hyderabad", row["href"])


class WorkspaceWebTests(unittest.TestCase):
    """The workspace as an operator meets it."""

    def client(self, workdir: Path):
        from founderos_atlas.web import create_app
        from founderos_atlas.workspace import (
            InMemoryCredentialProvider, ProfileRepository, ProfileService,
        )

        service = ProfileService(
            ProfileRepository(workdir / "workspace"),
            InMemoryCredentialProvider(),
        )
        app = create_app(
            profile_service=service, output_dir=workdir / "out",
            history_root=workdir / "out" / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_every_page_shows_where_it_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.client(Path(tmp))
            for path, expected in (("/advisor", "Analyze"),
                                   ("/topology", "Network"),
                                   ("/policy", "Operations")):
                with self.subTest(path=path):
                    page = client.get(path).data.decode()
                    bar = page[page.index("workspace-bar"):]
                    bar = bar[:bar.index("</div>")]
                    self.assertIn(expected, bar)
                    self.assertIn('aria-label="Breadcrumb"', page)

    def test_a_page_can_be_pinned_and_unpinned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.client(Path(tmp))
            client.post("/workspace/favourite", data={
                "kind": "page", "label": "Advisor", "href": "/advisor",
                "next": "/advisor",
            }, follow_redirects=True)
            page = client.get("/advisor").data.decode()
            self.assertIn("Pinned", page)
            rail = page[page.index("workspace-rail"):]
            self.assertIn("/advisor", rail)

            client.post("/workspace/favourite", data={
                "kind": "page", "label": "Advisor", "href": "/advisor",
                "next": "/advisor",
            }, follow_redirects=True)
            self.assertNotIn(
                "workspace-pins",
                client.get("/advisor").data.decode(),
            )

    def test_an_off_site_link_can_never_be_pinned(self) -> None:
        """The store holds places inside Atlas. A pinned absolute URL
        would turn a convenience list into a redirect surface — and the
        CENTRAL redirect validator decides what "inside Atlas" means,
        so browser backslash-normalisation ("/\\evil.net" -> a
        protocol-relative URL) cannot slip through either (PR-172
        review)."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.client(Path(tmp))
            for href in ("https://evil.example/x", "//evil.example/x",
                         "/\\evil.example", "\\evil.example",
                         "/%5cevil.example", "/%2f%2fevil.example",
                         "javascript:alert(1)", ""):
                with self.subTest(href=href):
                    client.post("/workspace/favourite", data={
                        "kind": "page", "label": "Evil", "href": href,
                        "next": "/advisor",
                    }, follow_redirects=True)
                    self.assertNotIn(
                        "evil.example",
                        client.get("/advisor").data.decode(),
                    )

    def test_the_palette_is_rbac_filtered_like_the_nav(self) -> None:
        """A viewer's Ctrl+K palette must not advertise administration
        pages the nav correctly hides — one predicate serves both
        (PR-172 review)."""

        import os
        from unittest.mock import patch

        from founderos_atlas.access import UserStore
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True, exist_ok=True)
            store = UserStore(workspace)
            store.create(username="sso-root", roles=("system-admin",))
            store.create(username="sso-viewer", roles=("viewer",))
            with patch.dict(os.environ, {
                "ATLAS_PROXY_SECRET": "proxy-shared-secret-1",
            }):
                app = create_app(
                    output_dir=Path(tmp) / "out",
                    workspace_root=workspace, auth_mode="proxy",
                )
            app.config.update(TESTING=True)
            client = app.test_client()

            def palette(user):
                payload = client.get("/api/workspace/palette", headers={
                    "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
                    "X-Atlas-Remote-User": user,
                }).get_json()
                return {
                    str(row.get("href") or "").split("?", 1)[0]
                    for row in payload["items"]
                }

            admin_hrefs = palette("sso-root")
            viewer_hrefs = palette("sso-viewer")
            self.assertIn("/users", admin_hrefs)
            self.assertNotIn("/users", viewer_hrefs)
            # Parity with enforcement: what the palette hides really is
            # denied, and what it shows really opens.
            denied = client.get("/users", headers={
                "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
                "X-Atlas-Remote-User": "sso-viewer",
            })
            self.assertEqual(403, denied.status_code)
            self.assertLess(0, len(viewer_hrefs))

    def test_the_palette_finds_pages_as_well_as_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.client(Path(tmp))
            payload = client.get("/api/search?q=policy").get_json()
            groups = {group["id"]: group for group in payload["groups"]}
            self.assertIn("pages", groups)
            labels = [row["label"] for row in groups["pages"]["results"]]
            self.assertIn("Policy", labels)

    def test_a_one_character_query_does_not_list_every_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.client(Path(tmp))
            payload = client.get("/api/search?q=p").get_json()
            self.assertNotIn(
                "pages", {group["id"] for group in payload["groups"]},
            )

    def test_a_device_page_offers_its_related_surfaces(self) -> None:
        from tests.test_polish import build_world

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            # GW is the fixture's stable, hostname-addressable device —
            # the same handle test_navigation uses.
            response = client.get("/devices/GW?scope=all")
            self.assertEqual(200, response.status_code)
            device_page = response.data.decode()
            rail = device_page[device_page.index("workspace-rail"):]
            for expected in ("Topology", "Configuration", "Timeline",
                             "Evidence", "Policy", "Incidents"):
                self.assertIn(expected, rail)
            # ...and it is now a recent place.
            self.assertIn("Recent", rail)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
