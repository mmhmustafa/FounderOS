"""Acceptance tests for PR-038 — Atlas Universal Search (SEARCH).

The front door to Atlas: one deterministic search box over the
Enterprise Graph and every workspace artifact — devices, interfaces
(including SVI-derived VLAN evidence), sites, topology links, profiles,
credential NAMES, predictions, investigations, changes, and discovery
history. Ranking is exact → canonical → prefix → partial with
historical objects after live ones; results are grouped with counts;
no fuzzy AI, no invented objects, never a secret.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest

from founderos_atlas.credentials import (
    CredentialSetRepository,
    CredentialSetService,
)
from founderos_atlas.federation import build_enterprise_graph
from founderos_atlas.search import (
    SearchIndex,
    SearchService,
    build_search_index,
    entries_from_graph,
    search_devices,
    search_enterprise,
    search_interfaces,
)
from founderos_atlas.workspace import InMemoryCredentialProvider

from tests.test_atlas_transport import PASSWORD
from tests.test_federation import (
    contribution,
    device,
    edge,
    hyderabad_network,
    secunderabad_network,
)
from tests.test_profile_isolation import FIXED, add_profile, make_service, run_discover


def lab_graph():
    """A1 (Gi0/1→A2, Gi0/2→GW), A2, shared GW, plus an SVI on A2."""

    hyd = contribution(
        "hyd",
        [
            device("A1", "10.0.0.1", serial="SER-A1",
                   interfaces=(("Gi0/1", "up"), ("Gi0/2", "up"))),
            device("A2", "10.0.0.2", serial="SER-A2",
                   interfaces=(("Gi0/1", "up"), ("Vlan20", "up"))),
            device("GW", "10.0.9.9", serial="SER-GW"),
        ],
        [
            edge("A1@10.0.0.1", "Gi0/1", "A2", "Gi0/1"),
            edge("A1@10.0.0.1", "Gi0/2", "GW", "Gi0/1"),
        ],
    )
    sec = contribution(
        "sec",
        [device("B1", "10.0.1.1", serial="SER-B1"),
         device("GW", "10.0.9.9", serial="SER-GW")],
        [edge("B1@10.0.1.1", "Gi0/1", "GW", "Gi0/2")],
    )
    return build_enterprise_graph((hyd, sec))


def lab_index() -> SearchIndex:
    return SearchIndex(entries_from_graph(lab_graph()))


class RankingAndMatchingTests(unittest.TestCase):
    def test_exact_device_by_hostname(self) -> None:
        response = search_enterprise(lab_index(), "A1")
        devices = next(g for g in response.groups if g.group_id == "devices")
        self.assertEqual("A1", devices.results[0].entry.title)
        self.assertEqual("exact", devices.results[0].rank_label)

    def test_partial_hostname_matches_after_exact(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution(
                    "hyd",
                    [device("SW1", "10.0.0.2"), device("SW10", "10.0.0.3"),
                     device("CORE-SW1", "10.0.0.4")],
                ),
            )
        )
        response = search_enterprise(SearchIndex(entries_from_graph(graph)), "SW1")
        devices = next(g for g in response.groups if g.group_id == "devices")
        titles = [hit.entry.title for hit in devices.results]
        self.assertEqual(["SW1", "SW10", "CORE-SW1"], titles)
        labels = [hit.rank_label for hit in devices.results]
        self.assertEqual(["exact", "prefix", "partial"], labels)

    def test_management_ip_finds_the_device(self) -> None:
        response = search_devices(lab_index(), "10.0.0.2")
        self.assertEqual(1, response.total)
        hit = response.groups[0].results[0]
        self.assertEqual("A2", hit.entry.title)
        self.assertEqual("management ip", hit.match_field)

    def test_serial_number_is_a_canonical_match(self) -> None:
        response = search_devices(lab_index(), "SER-GW")
        hit = response.groups[0].results[0]
        self.assertEqual("GW", hit.entry.title)
        self.assertEqual("canonical", hit.rank_label)

    def test_enterprise_id_resolves_canonically(self) -> None:
        graph = lab_graph()
        gw = next(d for d in graph.devices if d.hostname == "GW")
        response = search_devices(lab_index(), gw.enterprise_id)
        self.assertEqual("GW", response.groups[0].results[0].entry.title)

    def test_platform_search(self) -> None:
        response = search_devices(lab_index(), "IOSv")
        self.assertEqual(4, response.total)  # every device in the fixture

    def test_interface_search_shows_device_status_and_neighbor(self) -> None:
        response = search_interfaces(lab_index(), "Gi0/2")
        hit = response.groups[0].results[0]
        self.assertEqual("A1 Gi0/2", hit.entry.title)
        self.assertEqual("A1", hit.entry.detail["device"])
        self.assertEqual("up", hit.entry.detail["status"])
        self.assertEqual("GW", hit.entry.detail["neighbor"])

    def test_vlan_id_matches_the_discovered_svi(self) -> None:
        response = search_enterprise(lab_index(), "VLAN20")
        interfaces = next(
            g for g in response.groups if g.group_id == "interfaces"
        )
        self.assertEqual("A2 Vlan20", interfaces.results[0].entry.title)
        self.assertEqual("exact", interfaces.results[0].rank_label)

    def test_site_search_returns_a_site_group(self) -> None:
        response = search_enterprise(lab_index(), "Unknown")
        self.assertIn("sites", [g.group_id for g in response.groups])

    def test_empty_and_unmatched_queries_are_honest(self) -> None:
        index = lab_index()
        self.assertEqual(0, search_enterprise(index, "").total)
        self.assertEqual(0, search_enterprise(index, "   ").total)
        self.assertEqual(0, search_enterprise(index, "zz-not-a-thing").total)

    def test_grouping_counts_and_limits(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution(
                    "hyd",
                    [device(f"SW{i}", f"10.0.0.{i}") for i in range(1, 21)],
                ),
            )
        )
        response = SearchIndex(entries_from_graph(graph)).search(
            "SW", limit_per_group=5
        )
        devices = next(g for g in response.groups if g.group_id == "devices")
        self.assertEqual(20, devices.count)       # full count displayed
        self.assertEqual(5, len(devices.results))  # limited results

    def test_identical_evidence_yields_identical_results(self) -> None:
        first = search_enterprise(lab_index(), "gw").to_dict()
        second = search_enterprise(lab_index(), "gw").to_dict()
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )


class WorkspaceIndexTests(unittest.TestCase):
    """Index over a real discovered workspace: reports, history, rebuilds."""

    def build_world(self, workdir: Path):
        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        add_profile(service, "Secunderabad", "10.0.1.1")
        run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
        run_discover(
            workdir, service, secunderabad_network(), "Secunderabad",
            FIXED + timedelta(minutes=30),
        )
        return service

    def test_profiles_history_and_recent_are_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_world(workdir)
            index = build_search_index(workdir, service.list_profiles())
            response = search_enterprise(index, "Hyderabad")
            group_ids = [g.group_id for g in response.groups]
            self.assertIn("profiles", group_ids)
            self.assertIn("history", group_ids)
            recent = search_enterprise(index, "recent")
            self.assertIn("history", [g.group_id for g in recent.groups])
            # Historical entries carry the historical rank label.
            history = next(g for g in recent.groups if g.group_id == "history")
            self.assertIn("historical", history.results[0].rank_label)

    def test_live_objects_rank_before_historical_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_world(workdir)
            from founderos_atlas.path_intelligence import investigate_path_for_scope
            from founderos_atlas.workspace import profile_scope

            scope = profile_scope(workdir, "hyderabad", "Hyderabad")
            investigate_path_for_scope(
                "A1", "A2",
                output_dir=scope.output_dir,
                history_root=scope.history_root,
                generated_at=(FIXED + timedelta(hours=1)).isoformat(
                    timespec="seconds"
                ),
                profile_id="hyderabad",
            )
            index = build_search_index(workdir, service.list_profiles())
            response = search_enterprise(index, "A1")
            group_ids = [g.group_id for g in response.groups]
            self.assertIn("devices", group_ids)
            self.assertIn("investigations", group_ids)
            # The live device ranks before the historical investigation.
            self.assertLess(
                group_ids.index("devices"), group_ids.index("investigations")
            )
            flattened = [
                hit for group in response.groups for hit in group.results
            ]
            self.assertEqual("A1", flattened[0].entry.title)

    def test_index_rebuilds_automatically_when_evidence_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_world(workdir)
            search_service = SearchService()
            index = search_service.index_for(workdir, service.list_profiles())
            self.assertEqual(
                0, search_enterprise(index, "investigation").total
            )
            same = search_service.index_for(workdir, service.list_profiles())
            self.assertIs(index, same)  # unchanged evidence: cached
            from founderos_atlas.path_intelligence import investigate_path_for_scope
            from founderos_atlas.workspace import profile_scope

            scope = profile_scope(workdir, "hyderabad", "Hyderabad")
            investigate_path_for_scope(
                "A1", "GW",
                output_dir=scope.output_dir,
                history_root=scope.history_root,
                generated_at=(FIXED + timedelta(hours=1)).isoformat(
                    timespec="seconds"
                ),
                profile_id="hyderabad",
            )
            rebuilt = search_service.index_for(workdir, service.list_profiles())
            self.assertIsNot(index, rebuilt)
            self.assertGreater(
                search_enterprise(rebuilt, "investigation").total, 0
            )

    def test_credentials_are_indexed_by_name_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_world(workdir)
            credentials = CredentialSetService(
                CredentialSetRepository(workdir / "workspace"),
                InMemoryCredentialProvider(),
            )
            credentials.add_entry(
                set_name="Core Switches",
                label="primary readonly",
                username="atlas-ro",
                password=PASSWORD,
            )
            index = build_search_index(
                workdir,
                service.list_profiles(),
                credential_sets=credentials.list_sets(),
            )
            response = search_enterprise(index, "Core Switches")
            hits = next(g for g in response.groups if g.group_id == "credentials")
            self.assertEqual("Core Switches", hits.results[0].entry.title)
            serialized = json.dumps(
                search_enterprise(index, "Core Switches").to_dict()
            ) + json.dumps(search_enterprise(index, "atlas").to_dict())
            self.assertNotIn(PASSWORD, serialized)
            self.assertNotIn("atlas-ro", serialized)  # usernames stay out too


class PerformanceTests(unittest.TestCase):
    def test_large_enterprise_builds_and_searches_quickly(self) -> None:
        devices = [
            device(
                f"SW{i:03d}", f"10.{i // 250}.{(i // 50) % 5}.{i % 50 + 1}",
                serial=f"SER-{i:03d}",
                interfaces=(("Gi0/1", "up"), ("Gi0/2", "up")),
            )
            for i in range(500)
        ]
        edges = [
            edge(
                f"SW{i:03d}@10.{i // 250}.{(i // 50) % 5}.{i % 50 + 1}",
                "Gi0/2", f"SW{(i + 1) % 500:03d}", "Gi0/1",
            )
            for i in range(500)
        ]
        started = time.perf_counter()
        graph = build_enterprise_graph((contribution("big", devices, edges),))
        index = SearchIndex(entries_from_graph(graph))
        build_seconds = time.perf_counter() - started
        self.assertGreaterEqual(index.entry_count, 1500)
        started = time.perf_counter()
        for query in ("SW042", "10.0.1.7", "Gi0/2", "SER-499", "sw0"):
            search_enterprise(index, query)
        search_seconds = time.perf_counter() - started
        # Generous bounds: instant in practice, robust on slow CI.
        self.assertLess(build_seconds, 5.0)
        self.assertLess(search_seconds, 1.0)
        exact = search_devices(index, "SW042")
        self.assertEqual("SW042", exact.groups[0].results[0].entry.title)


class SearchGuiTests(unittest.TestCase):
    def build_world(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        add_profile(service, "Secunderabad", "10.0.1.1")
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

    def test_every_page_carries_the_search_experience(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/?scope=all").data
            self.assertIn(b"atlas-search-trigger", page)
            self.assertIn(b"Ctrl", page)
            self.assertIn(b"atlas-search-input", page)
            script = client.get("/static/atlas.js").data
            for marker in (b"/api/search", b"ArrowDown", b"Escape",
                           b"atlas-recent-searches", b"localStorage"):
                self.assertIn(marker, script)

    def test_api_search_returns_grouped_deterministic_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            payload = client.get("/api/search?q=GW").get_json()
            devices = next(
                g for g in payload["groups"] if g["id"] == "devices"
            )
            self.assertEqual(1, devices["count"])  # merged: exactly one GW
            result = devices["results"][0]
            self.assertEqual("GW", result["title"])
            self.assertEqual(95, result["detail"]["confidence_percent"])
            self.assertEqual(2, result["detail"]["observation_count"])
            self.assertEqual("exact", result["match"]["rank"])
            again = client.get("/api/search?q=GW").get_json()
            self.assertEqual(payload, again)
            self.assertNotIn(PASSWORD, json.dumps(payload))

    def test_api_search_by_ip_interface_and_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            by_ip = client.get("/api/search?q=10.0.0.2").get_json()
            devices = next(g for g in by_ip["groups"] if g["id"] == "devices")
            self.assertEqual("A2", devices["results"][0]["title"])
            by_iface = client.get("/api/search?q=Gi0/1").get_json()
            self.assertIn(
                "interfaces", [g["id"] for g in by_iface["groups"]]
            )
            empty = client.get("/api/search?q=zz-none").get_json()
            self.assertEqual(0, empty["total"])
            self.assertEqual([], empty["groups"])

    def test_device_details_page_from_a_search_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            payload = client.get("/api/search?q=GW").get_json()
            href = next(
                g for g in payload["groups"] if g["id"] == "devices"
            )["results"][0]["href"]
            page = client.get(href).data
            self.assertIn(b"GW", page)
            self.assertIn(b"SERIAL-GW", page)
            self.assertIn(b"Observed by Hyderabad", page)
            self.assertIn(b"Observed by Secunderabad", page)
            self.assertIn(b"Interfaces", page)
            self.assertIn(b"Identity confidence", page)
            self.assertNotIn(PASSWORD.encode(), page)

    def test_unknown_device_page_is_an_honest_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            response = client.get("/devices/ent:no-such-device")
            self.assertEqual(404, response.status_code)
            self.assertIn(b"Device not found", response.data)

    def test_search_sees_new_predictions_without_restart(self) -> None:
        """The index rebuild is automatic after evidence changes."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            before = client.get("/api/search?q=prediction").get_json()
            self.assertEqual(0, before["total"])
            client.get("/predict?scope=all")
            client.post(
                "/predict/run",
                data={"device": "GW", "interface": "Gi0/1"},
                follow_redirects=True,
            )
            after = client.get("/api/search?q=prediction").get_json()
            self.assertGreater(after["total"], 0)
            group = next(
                g for g in after["groups"] if g["id"] == "predictions"
            )
            self.assertIn("GW", group["results"][0]["title"])


class SearchModalLifecycleTests(unittest.TestCase):
    """PR-038 bug fix: the modal must start hidden and close reliably.

    Root cause of the original regression: ``.search-overlay`` declared
    ``display: flex``, and author CSS overrides the user-agent's
    ``[hidden] { display: none }`` rule — so the modal painted on page
    load and every close handler ran invisibly. These tests pin the
    explicit hidden state and the lifecycle wiring. (The Python test
    environment has no JS engine, so keyboard behavior is pinned at the
    source level; the live behavior was verified manually in a browser.)
    """

    def build_client(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_modal_starts_hidden_with_dialog_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertIn(
                '<div class="search-overlay" id="atlas-search" hidden'
                ' aria-hidden="true">',
                page,
            )
            self.assertIn('aria-modal="true"', page)
            self.assertIn('role="dialog"', page)

    def test_hidden_state_actually_hides_despite_display_flex(self) -> None:
        """THE regression pin: author CSS must define the hidden state."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            css = client.get("/static/atlas.css").data.decode("utf-8")
            self.assertIn(".search-overlay[hidden]", css)
            rule = css.split(".search-overlay[hidden]", 1)[1].split("}", 1)[0]
            self.assertIn("display: none", rule)

    def test_exactly_one_modal_and_backdrop_per_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            for path in ("/?scope=all", "/topology?scope=all", "/paths",
                         "/predict", "/credentials"):
                page = client.get(path).data.decode("utf-8")
                self.assertEqual(
                    1, page.count('id="atlas-search"'), path
                )
                self.assertEqual(
                    1, page.count('class="search-overlay"'), path
                )
                self.assertEqual(
                    1, page.count('id="atlas-search-input"'), path
                )

    def test_device_details_page_carries_the_same_single_modal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            payload = client.get("/api/search?q=A1").get_json()
            href = next(
                g for g in payload["groups"] if g["id"] == "devices"
            )["results"][0]["href"]
            page = client.get(href).data.decode("utf-8")
            self.assertEqual(1, page.count('id="atlas-search"'))
            self.assertIn('hidden aria-hidden="true"', page)

    def test_keyboard_lifecycle_wiring_is_single_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            script = client.get("/static/atlas.js").data.decode("utf-8")
            # One document-level keydown handler: Ctrl+K / Meta+K toggle
            # (with preventDefault against the browser default) + Escape.
            self.assertEqual(
                1, script.count('document.addEventListener("keydown"')
            )
            self.assertIn("event.ctrlKey || event.metaKey", script)
            toggle = script.split("event.ctrlKey || event.metaKey", 1)[1]
            self.assertIn("event.preventDefault()", toggle[:200])
            self.assertIn(
                "if (searchOverlay.hidden) openSearch(); else closeSearch();",
                script,
            )
            # Escape closes from inside the input too, ahead of navigation.
            input_handler = script.split(
                'searchInput.addEventListener("keydown"', 1
            )[1]
            self.assertLess(
                input_handler.index('"Escape"'),
                input_handler.index('"ArrowDown"'),
            )
            # Arrow/Enter navigation intact.
            self.assertIn('"ArrowUp"', script)
            self.assertIn('"Enter"', script)

    def test_open_close_focus_and_aria_are_managed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            script = client.get("/static/atlas.js").data.decode("utf-8")
            self.assertIn("lastFocused = document.activeElement", script)
            self.assertIn("lastFocused.focus()", script)
            self.assertIn('setAttribute("aria-hidden", "false")', script)
            self.assertIn('setAttribute("aria-hidden", "true")', script)
            # Reopening selects the preserved query instead of clearing it.
            self.assertIn("searchInput.select()", script)
            # Backdrop click closes (only the backdrop, not the panel).
            self.assertIn(
                "if (event.target === searchOverlay) closeSearch();", script
            )

    def test_results_are_replaced_never_appended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            script = client.get("/static/atlas.js").data.decode("utf-8")
            render = script.split("var renderResults", 1)[1]
            # The container is emptied before any result is appended.
            self.assertLess(
                render.index('container.textContent = ""'),
                render.index("container.appendChild"),
            )
            recent = script.split("var renderRecent", 1)[1]
            self.assertLess(
                recent.index('list.textContent = ""'),
                recent.index("list.appendChild"),
            )

    def test_search_behaviour_unchanged_by_the_fix(self) -> None:
        """No regression to ranking or grouped results."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            payload = client.get("/api/search?q=A1").get_json()
            devices = next(
                g for g in payload["groups"] if g["id"] == "devices"
            )
            self.assertEqual("A1", devices["results"][0]["title"])
            self.assertEqual("exact", devices["results"][0]["match"]["rank"])


if __name__ == "__main__":
    unittest.main()
