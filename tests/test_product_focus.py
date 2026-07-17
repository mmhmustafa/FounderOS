"""PR-047A (FOCUS) — product simplification and consistency tests.

Atlas grew eighteen top-level navigation items and four pages answering one
question. These tests pin the accepted product decisions:

- navigation is six workflows, not eighteen destinations, and **nothing was
  removed** — every view is still reachable;
- Changes / Configuration / Discoveries / Evidence are one workflow with one
  front door (Timeline);
- SSH and HTTPS are device *actions*, not product capabilities in the menu;
- confidence is shown only when it should change what the reader does;
- page titles say what the navigation says.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from founderos_atlas.web.confidence import confidence_detail, confidence_display
from founderos_atlas.web.models import (
    NAV_GROUPS,
    NAV_GROUP_FOR_ITEM,
    nav_group_for,
    timeline_activity,
)


# The full set of destinations that existed before FOCUS. Every one must still
# resolve: this PR reorganised the product, it did not remove any of it.
LEGACY_ROUTES = (
    "/", "/advisor", "/discovery", "/profiles", "/credentials", "/topology",
    "/configuration", "/memory", "/policy", "/console", "/management",
    "/predict", "/paths", "/compass", "/history", "/changes", "/incidents",
    "/settings",
)


def _client(tmp: Path):
    from founderos_atlas.web import create_app

    app = create_app(
        output_dir=tmp,
        history_root=tmp / ".atlas" / "history",
        workspace_root=tmp / "workspace",
    )
    app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
    return app.test_client()


class NavigationStructureTests(unittest.TestCase):
    def test_navigation_is_six_workflows(self) -> None:
        self.assertEqual(6, len(NAV_GROUPS))
        self.assertEqual(
            ["Mission", "Network", "Timeline", "Policy", "Analyze", "Setup"],
            [group.label for group in NAV_GROUPS],
        )

    def test_every_view_belongs_to_exactly_one_workflow(self) -> None:
        seen: dict[str, str] = {}
        for group in NAV_GROUPS:
            for item in group.items:
                self.assertNotIn(item.key, seen, f"{item.key} in two groups")
                seen[item.key] = group.key
        self.assertEqual(seen, NAV_GROUP_FOR_ITEM)

    def test_the_four_past_pages_are_one_workflow(self) -> None:
        """Changes, Configuration, Discoveries and Evidence answered one
        question from four top-level items. They are one workflow now."""

        for key in ("changes", "configuration", "history", "memory", "timeline"):
            self.assertEqual("timeline", nav_group_for(key), key)

    def test_device_access_is_not_a_workflow(self) -> None:
        """SSH and web management are actions on a device, not menu items."""

        keys = {item.key for group in NAV_GROUPS for item in group.items}
        self.assertNotIn("console", keys)
        self.assertNotIn("management", keys)
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(Path(tmp))
            # Device Access is the one page: SSH and web are two ways into the
            # same device, so they are not two pages.
            self.assertEqual(200, client.get("/console").status_code)
            # The old Web Management URL still lands somewhere true.
            self.assertEqual(302, client.get("/management").status_code)

    def test_compass_is_frozen_not_removed(self) -> None:
        keys = {i.key for g in NAV_GROUPS for i in g.items}
        self.assertIn("compass", keys)
        self.assertEqual("analyze", nav_group_for("compass"))

    def test_unknown_view_never_highlights_the_wrong_workflow(self) -> None:
        self.assertEqual("console", nav_group_for("console"))

    def test_nothing_was_removed_every_legacy_route_still_resolves(self) -> None:
        """Every pre-FOCUS destination still lands somewhere true. A 302 counts:
        /management redirects to Device Access, which absorbed it — the URL was
        kept alive deliberately so an old link never 404s."""

        with tempfile.TemporaryDirectory() as tmp:
            client = _client(Path(tmp))
            for route in LEGACY_ROUTES:
                self.assertIn(
                    client.get(route).status_code, (200, 302), f"{route} regressed"
                )
                # ...and a redirect must actually arrive.
                self.assertEqual(
                    200,
                    client.get(route, follow_redirects=True).status_code,
                    f"{route} redirects nowhere",
                )

    def test_sidebar_groups_every_view_under_its_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = _client(Path(tmp)).get("/policy").get_data(as_text=True)
            # Six workflow labels orient the reader...
            for label in ("Mission", "Network", "Timeline", "Policy", "Analyze", "Setup"):
                self.assertIn(label, page)
            # ...and a single-view group is its own link, not a label above one
            # lonely child.
            self.assertIn('href="/topology"', page)
            self.assertIn('href="/policy"', page)

    def test_expert_views_stay_one_click_away_from_anywhere(self) -> None:
        """Grouping organises the sidebar; it must not bury the tools an
        engineer lives in. Mission is the front door, never a gate."""

        with tempfile.TemporaryDirectory() as tmp:
            page = _client(Path(tmp)).get("/").get_data(as_text=True)
            for href in (
                "/predict", "/paths", "/topology", "/history", "/compass",
                "/changes", "/configuration", "/evidence", "/timeline", "/policy",
                "/advisor", "/incidents", "/discovery", "/settings",
            ):
                self.assertIn(f'href="{href}"', page, f"{href} not in sidebar")


class TimelineWorkflowTests(unittest.TestCase):
    def test_timeline_page_renders_and_offers_the_four_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = _client(Path(tmp)).get("/timeline").get_data(as_text=True)
            self.assertIn("Events", page)
            for href in ("/changes", "/configuration", "/history",
                         "/evidence", "/audit"):
                self.assertIn(href, page)

    def test_activity_merges_configuration_changes_and_discoveries(self) -> None:
        class Event:
            occurred_at = "2026-07-14T12:00:00+00:00"
            device_id = "dev-1"
            hostname = "core1"
            network = "Lab"
            summary = "3 lines changed"
            change_count = 3
            discovery_session = "sess-1"
            highest_severity = "medium"

        rows = [
            {
                "started_at_iso": "2026-07-14T13:00:00+00:00",
                "device_count": 9,
                "relationship_count": 12,
                "network_status": "healthy",
                "profile": "Lab",
                "record_id": "rec-1",
            }
        ]
        activity = timeline_activity([Event()], rows)
        self.assertEqual(2, len(activity))
        # Newest first, across both kinds.
        self.assertEqual("discovery", activity[0]["kind"])
        self.assertEqual("configuration", activity[1]["kind"])

    def test_configuration_rows_render(self) -> None:
        """The lab has discoveries but no configuration *changes* yet, so a live
        page only ever exercises the discovery branch. This renders the other
        one — at every severity — so a template bug there cannot hide until the
        first real change lands."""

        from flask import render_template

        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_dir=Path(tmp), history_root=Path(tmp) / ".atlas" / "history"
            )
            app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
            activity = [
                {
                    "occurred_at": "15-Jul-2026 06:15",
                    "kind": "configuration",
                    "title": "core1 configuration changed",
                    "detail": "3 lines changed",
                    "device_id": "frr:core1",
                    "hostname": "core1",
                    "network": "lab",
                    "severity": severity,
                    "discovery_session": "sess-1",
                    "change_count": 3,
                    "href": "/configuration/frr%3Acore1",
                    "when": "15-Jul-2026 06:15",
                    "actor": None,
                    "provenance": "configuration memory · session sess-1",
                }
                for severity in ("high", "medium", "low")
            ]
            from founderos_atlas.listing import paginate
            from founderos_atlas.web.chronicle import ChronicleFilter

            with app.test_request_context("/timeline"):
                html = render_template(
                    "timeline.html",
                    activity=activity,
                    page=paginate(activity, 1, 50),
                    filters=ChronicleFilter(),
                    filter_args={},
                    kind_counts={"configuration": 3},
                    option_actors=[],
                    option_sites=[],
                    change_count=3,
                    discovery_count=0,
                    totals={"devices": 1, "versions": 2},
                    evidence_totals={"sessions": 1, "evidence_records": 5},
                    nav_groups=NAV_GROUPS,
                    active="timeline",
                    active_group=nav_group_for("timeline"),
                    product="Atlas",
                )
            self.assertIn("core1 configuration changed", html)
            self.assertIn("3 lines changed", html)
            # severity drives the badge: high -> failed, medium -> warning
            self.assertIn("hop-badge-failed", html)
            self.assertIn("hop-badge-warning", html)
            self.assertIn("/configuration/frr%3Acore1", html)

    def test_activity_carries_the_change_to_discovery_link(self) -> None:
        """The seam a future Change -> Impact capability follows: a
        configuration change knows the discovery that observed it."""

        class Event:
            occurred_at = "2026-07-14T12:00:00+00:00"
            device_id = "dev-1"
            hostname = "core1"
            network = "Lab"
            summary = "changed"
            change_count = 1
            discovery_session = "sess-42"
            highest_severity = "low"

        activity = timeline_activity([Event()], [])
        self.assertEqual("sess-42", activity[0]["discovery_session"])
        self.assertEqual("dev-1", activity[0]["device_id"])


class ConfidencePresentationTests(unittest.TestCase):
    def test_confident_deterministic_results_say_nothing(self) -> None:
        """108 of 108 rows reading "high (85%)" is noise, not information."""

        for band in ("very-high", "high"):
            self.assertIsNone(
                confidence_display({"band": band, "percent": 85, "basis": "x"})
            )

    def test_confidence_is_shown_when_it_changes_the_decision(self) -> None:
        for band, label in (
            ("medium", "Medium confidence"),
            ("low", "Low confidence"),
            ("unknown", "Unknown"),
        ):
            shown = confidence_display({"band": band, "percent": 40, "basis": "x"})
            self.assertIsNotNone(shown, band)
            self.assertEqual(label, shown["label"])

    def test_unknown_quotes_no_percentage(self) -> None:
        """An Unknown has no measurement to quote; printing the 5% floor would
        imply one."""

        shown = confidence_display({"band": "unknown", "percent": 5, "basis": "x"})
        self.assertIsNone(shown["percent"])

    def test_conflicting_evidence_is_always_surfaced(self) -> None:
        shown = confidence_display(
            {"band": "very-high", "percent": 92, "basis": "x"}, conflicting=True
        )
        self.assertIsNotNone(shown)
        self.assertEqual("Conflicting evidence", shown["label"])

    def test_detail_view_always_discloses_fully(self) -> None:
        text = confidence_detail({"band": "high", "percent": 85, "basis": "direct"})
        self.assertIn("high", text)
        self.assertIn("85", text)

    def test_missing_confidence_is_handled(self) -> None:
        self.assertIsNone(confidence_display(None))
        self.assertEqual("—", confidence_detail(None))


class ConsistencyTests(unittest.TestCase):
    def test_page_titles_are_not_double_prefixed(self) -> None:
        """base.html already renders 'Atlas — {title}'."""

        templates = Path("src/founderos_atlas/web/templates")
        offenders = [
            path.name
            for path in templates.glob("*.html")
            if "{% block title %}Atlas —" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)

    def test_the_universal_device_action_has_no_dead_links(self) -> None:
        """The Investigate action pointed at /investigate, which never existed."""

        macro = Path(
            "src/founderos_atlas/web/templates/_device_actions.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/investigate", macro)
        self.assertIn("/paths?device=", macro)

    def test_no_template_links_to_a_route_that_does_not_exist(self) -> None:
        """The general form of the /investigate bug: a button that 404s.

        Every literal href in every template is matched against the real URL
        map, so this class of defect cannot come back unnoticed.
        """

        import re

        from werkzeug.exceptions import MethodNotAllowed, NotFound
        from werkzeug.routing import RequestRedirect

        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_dir=Path(tmp), history_root=Path(tmp) / ".atlas" / "history"
            )
            adapter = app.url_map.bind("127.0.0.1")

            def resolves(href: str) -> bool:
                try:
                    adapter.match(href.split("?")[0].split("#")[0])
                except NotFound:
                    return False
                except (RequestRedirect, MethodNotAllowed):
                    return True
                return True

            dead: list[str] = []
            for tpl in Path("src/founderos_atlas/web/templates").glob("*.html"):
                text = tpl.read_text(encoding="utf-8")
                # Literal hrefs only — Jinja-built URLs are not statically known.
                for href in re.findall(r'href="(/[^"{}]*)"', text):
                    if not resolves(href):
                        dead.append(f"{tpl.name}: {href}")
            self.assertEqual([], dead, "templates link to non-existent routes")

    def test_device_lists_offer_device_actions(self) -> None:
        """Decision 3: any device list, not just the device pages."""

        templates = Path("src/founderos_atlas/web/templates")
        for filename in (
            "topology.html", "device.html", "timeline.html",
            "evidence_index.html", "evidence_device.html",
            "configuration.html", "paths.html", "advisor.html",
            "console_index.html",
        ):
            text = (templates / filename).read_text(encoding="utf-8")
            self.assertTrue(
                "device_actions(" in text or "device_menu(" in text,
                f"{filename} shows devices but offers no device actions",
            )

    def test_every_device_action_answers_the_web_question(self) -> None:
        """If a surface shows a device's actions, it answers BOTH questions.

        Passing `web=` is what makes the macro answer at all — without it the
        row silently offers SSH only, which is how the Configuration page ended
        up listing nine devices with no web action while the resolver sat right
        there. Omission is invisible in review, so it is asserted here instead:
        every call must ask, and the macro greys the answer when there is no
        verified endpoint.
        """

        import re

        templates = Path("src/founderos_atlas/web/templates")
        missing: list[str] = []
        for path in templates.glob("*.html"):
            if path.name == "_device_actions.html":
                continue  # the macro's own definition and docs
            text = path.read_text(encoding="utf-8")
            # Each call, across line breaks, up to its closing paren.
            for call in re.findall(r"device_actions\((?:[^()]|\([^()]*\))*\)", text):
                if "web=" not in call:
                    missing.append(f"{path.name}: {' '.join(call.split())[:70]}")
        self.assertEqual(
            [], missing, "device actions rendered without asking about web access"
        )

    def test_console_offers_web_access_and_greys_it_when_unavailable(self) -> None:
        """The device-access page answers both questions for every device.

        It previously asked only about SSH — it listed every device and never
        mentioned web access at all, even though the resolver was right there.
        Where no web endpoint is verified the action is greyed rather than
        absent: an empty cell reads as "Atlas didn't check".
        """

        console = Path(
            "src/founderos_atlas/web/templates/console_index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("web=web", console)
        # ...and the write side lives beside the action it enables.
        self.assertIn("js-verify-web", console)
        self.assertIn("js-define-web", console)

        macro = Path(
            "src/founderos_atlas/web/templates/_device_actions.html"
        ).read_text(encoding="utf-8")
        # Asking about web is answered either way: a live button or a greyed one.
        self.assertIn("disabled", macro)
        # ...and the greyed one always carries its reason.
        self.assertIn('title="{{ web.reason }}"', macro)

        css = Path("src/founderos_atlas/web/static/atlas.css").read_text(encoding="utf-8")
        self.assertIn(".btn[disabled]", css)

    def test_the_ui_does_not_name_internal_layers_at_the_operator(self) -> None:
        """The page is Evidence; the layer behind it is Enterprise Memory. The
        operator is shown the former and never sent looking for the latter.

        PR-047B refined this rather than reversed it. The storage internals are
        kept for administrators in one collapsed "Enterprise Memory — System
        Details" section, and naming the layer *there* is the point: that
        section is where someone who wants the storage engine should look. The
        rule is now about placement, not the phrase — the operator's page must
        not name it; the administrator's drawer may.
        """

        templates = Path("src/founderos_atlas/web/templates")
        offenders = []
        for path in templates.glob("*.html"):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "Device memory" in line:
                    offenders.append(f"{path.name}:{number}")
                if "Enterprise Memory" in line and "System Details" not in line:
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual([], offenders)

    def test_titles_match_their_navigation_labels(self) -> None:
        templates = Path("src/founderos_atlas/web/templates")
        for filename, expected in (
            ("history.html", "Discoveries"),
            ("evidence_index.html", "Evidence"),
            ("paths.html", "Investigate"),
            ("timeline.html", "Timeline"),
        ):
            text = (templates / filename).read_text(encoding="utf-8")
            self.assertIn(
                f"{{% block title %}}{expected}{{% endblock %}}", text, filename
            )


if __name__ == "__main__":
    unittest.main()
