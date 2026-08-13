"""Row action menus (PR-178.1): native disclosure, and a menu you can see.

Two defects measured on the live estate, and the contracts that keep
them fixed:

1. The trigger carried ``role="button"`` + ``aria-haspopup="menu"`` with
   none of the rest of the ARIA menu pattern — discarding the
   expanded/collapsed state a native ``<details>`` announces for free.
   The decision (adversarial review §9) is NATIVE DISCLOSURE: no role
   override, no aria-haspopup, and deliberately NO arrow-key navigation
   — arrow keys are the ARIA-menu expectation, and adding them to a
   disclosure builds exactly the half-menu the pattern rules forbid.

2. The list is ``position: absolute`` inside ``.table-scroll``
   (``overflow-x: auto``), and an absolutely positioned box cannot
   escape an overflow ancestor on its containing-block chain — a
   last-row menu rendered 570px of unreachable items, and at 375px it
   opened entirely outside the viewport. Proven by hit test: only
   ``position: fixed`` paints outside the scroller. The enhancement
   switches the OPEN list to fixed at viewport-clamped coordinates,
   closes on any scroll, and resets on close. CSS keeps ``absolute`` so
   the no-JS baseline is exactly today's behaviour.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/founderos_atlas/web/static"
TEMPLATES = ROOT / "src/founderos_atlas/web/templates"


class MenuSemanticsTests(unittest.TestCase):
    """Native disclosure, whole — not half of two patterns."""

    def test_no_action_menu_summary_overrides_its_native_role(self) -> None:
        """role="button" on an action-menu <summary> silences the
        expanded/collapsed announcement the element makes natively.

        Scoped to ``details.action-menu`` — the row action menus this PR
        owns. (Seven non-menu disclosure summaries elsewhere carry a
        plain role="button" with no menu claim; they are a separate,
        lesser residual, recorded in the handover, not silently fixed
        here.)"""

        offenders = []
        for path in sorted(TEMPLATES.glob("*.html")):
            body = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r'<details class="action-menu">.*?(<summary[^>]*>)',
                body, re.DOTALL,
            ):
                summary_tag = match.group(1)
                if "role=" in summary_tag:
                    offenders.append(f"{path.name}: {summary_tag[:60]}")
        self.assertEqual([], offenders, "action-menu summaries must keep native semantics")

    def test_no_incomplete_aria_menu_semantics_remain(self) -> None:
        """aria-haspopup promises an ARIA menu; the list is ordinary
        links inside a disclosure. Promise nothing you don't deliver.
        (Attribute form only — prose in comments may name the thing.)"""

        offenders = []
        for path in sorted(TEMPLATES.glob("*.html")):
            body = path.read_text(encoding="utf-8")
            if "aria-haspopup=" in body:
                offenders.append(f"{path.name}: aria-haspopup")
            if 'role="menu"' in body or 'role="menuitem"' in body:
                offenders.append(f"{path.name}: role=menu(item)")
        self.assertEqual([], offenders)

    def test_the_trigger_keeps_its_row_aware_accessible_name(self) -> None:
        macro = (TEMPLATES / "_entity_actions.html").read_text(encoding="utf-8")
        self.assertIn('aria-label="{{ label }} for {{ name }}"', macro)
        changes = (TEMPLATES / "changes.html").read_text(encoding="utf-8")
        self.assertIn(
            'aria-label="Actions for this change on', changes,
            "the hand-rolled Changes menu keeps its row-aware name",
        )

    def test_no_arrow_key_navigation_was_added_to_the_disclosure(self) -> None:
        """Arrow keys are the ARIA-menu expectation. A disclosure of
        links navigates by Tab; adding arrows would rebuild the
        forbidden half-menu. The menu enhancement section must not
        touch Arrow keys (Ctrl+K search legitimately does, below it)."""

        js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        menu_section = js.split("-- Entity action menus")[1].split(
            "-- Responsive navigation drawer"
        )[0]
        self.assertNotIn("Arrow", menu_section)
        self.assertNotIn("roving", menu_section)
        self.assertNotIn("tabindex", menu_section)

    def test_escape_and_outside_click_still_close_and_single_open_holds(self) -> None:
        js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        # One close implementation, called from Escape, outside click,
        # and the scroll-close below.
        self.assertIn("var closeMenus = function (except)", js)
        self.assertIn('document.querySelectorAll("details.action-menu[open]")', js)
        self.assertIn('} else if (event.key === "Escape") {', js)
        self.assertIn("closeMenus(null);", js)


class MenuPositioningTests(unittest.TestCase):
    """The open list escapes the scroll container — by position:fixed,
    set by JS, never by CSS alone (which cannot do it)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "atlas.css").read_text(encoding="utf-8")

    def test_css_keeps_absolute_as_the_no_js_baseline(self) -> None:
        """position:fixed in the stylesheet would anchor a no-JS menu to
        the viewport with auto offsets — it must only ever be applied by
        the script, on open."""

        match = re.search(
            r"^\.action-menu-list \{(.*?)\}", self.css, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(match, "the .action-menu-list rule must exist")
        self.assertIn("position: absolute", match.group(1))
        self.assertNotIn("fixed", match.group(1))

    def test_the_open_list_switches_to_fixed(self) -> None:
        self.assertIn('list.style.position = "fixed";', self.js)

    def test_the_switch_hangs_off_the_toggle_event_in_capture(self) -> None:
        # toggle does not bubble; only capture reaches it document-wide.
        self.assertIn('document.addEventListener("toggle", function (event) {', self.js)
        match = re.search(
            r'addEventListener\("toggle",.*?\}, true\);', self.js, re.DOTALL
        )
        self.assertIsNotNone(match, "toggle listener must use capture")

    def test_coordinates_are_viewport_clamped_and_flip(self) -> None:
        """Right-aligned to the trigger, flipped upward at the bottom
        edge, clamped inside both viewport axes."""

        self.assertIn("document.documentElement.clientWidth", self.js)
        self.assertIn("document.documentElement.clientHeight", self.js)
        self.assertIn("anchor.right - size.width", self.js)
        self.assertIn("anchor.top - gap - size.height", self.js)

    def test_scroll_closes_the_menu_rather_than_tracking_it(self) -> None:
        """A fixed list no longer follows its trigger. Capture catches
        the page AND every inner scroll container (.table-scroll)."""

        match = re.search(
            r'addEventListener\("scroll",.*?closeMenus\(\);.*?\}, true\);',
            self.js, re.DOTALL,
        )
        self.assertIsNotNone(match)

    def test_close_resets_every_inline_style_it_set(self) -> None:
        """A reopened menu must start from the stylesheet, not from the
        previous open's coordinates."""

        reset = self.js.split("var resetMenuList")[1].split("};")[0]
        for prop in ("position", "top", "left", "right", "width"):
            self.assertIn(f'list.style.{prop} = "";', reset)

    def test_the_width_is_locked_before_the_switch(self) -> None:
        """position:fixed re-resolves shrink-to-fit against the
        viewport; locking the measured width prevents reflow mid-open."""

        self.assertIn('list.style.width = size.width + "px";', self.js)

    def test_the_scroll_containers_keep_their_overflow(self) -> None:
        """The fix must not be 'remove overflow-x' — tables still scroll
        inside their region at every width."""

        self.assertIn("overflow-x: auto", self.css.split(".table-scroll {")[1].split("}")[0])


class NoJsBaselineTests(unittest.TestCase):
    def test_the_menu_is_server_rendered_and_complete_without_js(self) -> None:
        """The macro emits the full closed <details> — no template, no
        clone-on-open, nothing the script must build for the menu to
        exist. (On-demand DOM was explicitly rejected: adversarial
        review §11.)"""

        macro = (TEMPLATES / "_entity_actions.html").read_text(encoding="utf-8")
        self.assertIn("<details class=\"action-menu\">", macro)
        self.assertIn("<ul class=\"action-menu-list\">", macro)
        self.assertNotIn("<template", macro)
        js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        self.assertNotIn("cloneNode", js.split("-- Entity action menus")[1].split(
            "-- Responsive navigation drawer")[0])


class WebActionGroupTests(unittest.TestCase):
    """linking.py's web group reproduces EVERY branch of the inline
    device_actions web block — the one capability that was unique to the
    inline buttons, and the reason retiring them loses nothing."""

    HTTPS_WEB = {
        "device_id": "cisco-ios:gw", "hostname": "GW",
        "has_https": True, "http_only": False,
        "https_url": "https://10.0.9.9:8443", "http_url": None,
        "tls_summary": "Self-signed",
        "certificate_warnings": [
            "The certificate is self-signed — common on network equipment, "
            "and not proof of identity."
        ],
        "reason": "",
    }
    HTTP_WEB = {
        "device_id": "cisco-ios:sw", "hostname": "SW",
        "has_https": False, "http_only": True,
        "https_url": None, "http_url": "http://10.0.9.8",
        "tls_summary": None, "certificate_warnings": [],
        "reason": "",
    }
    UNVERIFIED_WEB = {
        "device_id": "cisco-ios:rt", "hostname": "RT",
        "has_https": False, "http_only": False,
        "https_url": None, "http_url": None,
        "tls_summary": None, "certificate_warnings": [],
        "reason": "No web management endpoint is verified for this device.",
    }

    def _actions(self, web):
        from founderos_atlas.web.linking import device_entity_actions

        return device_entity_actions(
            device_id="ent:gw", hostname="GW", scope_id="all",
            ssh_target=None, web=web,
        )

    def test_https_offers_open_and_copy_with_the_certificate_flag(self) -> None:
        actions = {a.key: a for a in self._actions(self.HTTPS_WEB)}
        self.assertIn("web", actions)
        self.assertIn("web-copy", actions)
        self.assertNotIn("web-insecure", actions)
        self.assertEqual("Open HTTPS", actions["web"].display_label)
        self.assertEqual("https://10.0.9.9:8443", actions["web"].href)
        self.assertTrue(actions["web"].external)
        self.assertIn("self-signed", actions["web"].flag)
        self.assertIn("certificate: Self-signed", actions["web"].title)
        self.assertEqual("Copy HTTPS URL", actions["web-copy"].display_label)
        self.assertIn("never includes a password", actions["web-copy"].title)

    def test_a_clean_certificate_raises_no_flag(self) -> None:
        clean = dict(self.HTTPS_WEB, certificate_warnings=[], tls_summary="Trusted")
        actions = {a.key: a for a in self._actions(clean)}
        self.assertIsNone(actions["web"].flag)
        self.assertNotIn("certificate:", actions["web"].title)

    def test_http_only_stays_explicitly_insecure(self) -> None:
        """The exact wording survives: never a generic "Web" action that
        hides the insecurity."""

        actions = {a.key: a for a in self._actions(self.HTTP_WEB)}
        self.assertIn("web-insecure", actions)
        self.assertNotIn("web", actions)
        self.assertEqual(
            "Open HTTP — Insecure", actions["web-insecure"].display_label
        )
        self.assertIn("travels in the clear", actions["web-insecure"].title)
        self.assertEqual("SW", actions["web-insecure"].hostname)
        self.assertEqual("cisco-ios:sw", actions["web-insecure"].device_id)
        self.assertEqual("Copy HTTP URL", actions["web-copy"].display_label)

    def test_resolved_but_unverified_is_greyed_with_the_actual_reason(self) -> None:
        """"Atlas checked, and here is why not" — never an empty cell."""

        actions = {a.key: a for a in self._actions(self.UNVERIFIED_WEB)}
        self.assertIn("web", actions)
        self.assertFalse(actions["web"].available)
        self.assertEqual(
            "No web management endpoint is verified for this device.",
            actions["web"].reason,
        )

    def test_unresolved_web_renders_no_web_item_at_all(self) -> None:
        """web=None means the caller could not resolve web access —
        exactly the inline macro's behaviour (it rendered nothing)."""

        keys = {a.key for a in self._actions(None)}
        self.assertFalse({"web", "web-insecure", "web-copy"} & keys)

    def test_web_actions_sit_with_ssh_in_the_canonical_order(self) -> None:
        from founderos_atlas.web.linking import ACTION_ORDER

        keys = [a.key for a in self._actions(self.HTTPS_WEB)]
        self.assertEqual(keys, [k for k in ACTION_ORDER if k in keys])
        self.assertLess(keys.index("ssh"), keys.index("web"))
        self.assertLess(keys.index("web"), keys.index("compass"))


class HonestAvailabilityTests(unittest.TestCase):
    """The menu may assert store absence ONLY when a caller consulted the
    store. Before PR-178.1 the strong claim rendered whenever the record
    id was missing — a stated reason nobody had checked."""

    def _actions(self, **kwargs):
        from founderos_atlas.web.linking import device_entity_actions

        defaults = dict(
            device_id=None, hostname="unresolved-peer", scope_id="all",
            ssh_target=None,
        )
        defaults.update(kwargs)
        return {a.key: a for a in device_entity_actions(**defaults)}

    def test_unestablished_absence_states_only_the_addressing_fact(self) -> None:
        actions = self._actions()  # no record id, flags not established
        for key in ("evidence", "configuration"):
            self.assertFalse(actions[key].available)
            self.assertIn("cannot be opened from here", actions[key].reason)
        self.assertNotIn("records are stored", actions["evidence"].reason)
        self.assertNotIn("is held", actions["configuration"].reason)

    def test_established_absence_keeps_the_strong_claim(self) -> None:
        actions = self._actions(
            memory_device_id="cisco-ios:gw",
            has_evidence=False, has_configuration=False,
        )
        self.assertEqual(
            "no evidence records are stored for unresolved-peer in this scope",
            actions["evidence"].reason,
        )
        self.assertEqual(
            "no configuration is held for unresolved-peer in this scope",
            actions["configuration"].reason,
        )

    def test_a_record_id_alone_keeps_the_links_available(self) -> None:
        """Tri-state None must not change what renders today: with an
        addressable record the links stay live."""

        actions = self._actions(memory_device_id="cisco-ios:gw")
        self.assertTrue(actions["evidence"].available)
        self.assertTrue(actions["configuration"].available)


class RowMigrationTests(unittest.TestCase):
    """Evidence and Configuration TABLE ROWS use the shared menu; detail
    surfaces deliberately keep the inline buttons (one device, not fifty)."""

    def test_evidence_and_configuration_rows_use_the_shared_menu(self) -> None:
        for name in ("evidence_index.html", "configuration.html"):
            body = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertNotIn("device_actions(", body, name)
            self.assertIn("entity_menu(device_menu(", body, name)

    def test_the_two_dead_imports_are_gone(self) -> None:
        changes = (TEMPLATES / "changes.html").read_text(encoding="utf-8")
        self.assertNotIn('from "_entity_actions.html" import', changes)
        topology = (TEMPLATES / "topology.html").read_text(encoding="utf-8")
        self.assertNotIn('from "_device_actions.html" import', topology)

    def test_detail_surfaces_keep_inline_device_actions(self) -> None:
        for name in (
            "device.html", "evidence_device.html", "configuration_device.html",
            "paths.html", "advisor.html", "console_index.html",
        ):
            body = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn("device_actions(", body, name)


class StoreMemoisationTests(unittest.TestCase):
    """ManagementServiceStore's read path parses once per file version —
    per INSTANCE, stat-validated, never process-global (the PR-176 rule)."""

    def _counting_store(self, path):
        from founderos_atlas.management.store import ManagementServiceStore

        store = ManagementServiceStore(path)
        calls = []
        original = store._load

        def counted():
            calls.append(1)
            return original()

        store._load = counted
        return store, calls

    def test_repeated_reads_parse_once(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "management-services.json"
            path.write_text(json.dumps({"services": [], "overrides": []}))
            store, calls = self._counting_store(path)
            for _ in range(50):
                store.services_for("cisco-ios:gw")
            self.assertEqual(1, len(calls), "one parse per file version")

    def test_a_write_through_the_store_is_never_served_stale(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "management-services.json"
            store, _ = self._counting_store(path)
            self.assertEqual((), store.services_for("cisco-ios:gw"))
            store.define_endpoint(
                "cisco-ios:gw", url="https://10.0.9.9:8443", protocol="https",
                address="10.0.9.9", port=8443, user="netops",
            )
            found = store.services_for("cisco-ios:gw")
            self.assertEqual(1, len(found))
            self.assertEqual("https://10.0.9.9:8443", found[0].url)

    def test_an_external_write_is_noticed(self) -> None:
        """Another process (or another store instance) rewriting the file
        must be seen: the memo is validated against (mtime_ns, size)."""

        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "management-services.json"
            path.write_text(json.dumps({"services": [], "overrides": []}))
            store, _ = self._counting_store(path)
            self.assertEqual((), store.services_for("cisco-ios:gw"))
            path.write_text(json.dumps({
                "services": [{
                    "device_id": "cisco-ios:gw", "address": "10.0.9.9",
                    "protocol": "https", "port": 443,
                    "verification": "verified",
                }],
                "overrides": [],
            }))
            self.assertEqual(1, len(store.services_for("cisco-ios:gw")))

    def test_a_missing_file_stays_empty_and_never_caches_a_ghost(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "management-services.json"
            store, _ = self._counting_store(path)
            self.assertEqual((), store.services_for("cisco-ios:gw"))
            store.define_endpoint(
                "cisco-ios:gw", url="https://10.0.9.9", protocol="https",
                address="10.0.9.9", port=443, user="netops",
            )
            self.assertEqual(1, len(store.services_for("cisco-ios:gw")))


if __name__ == "__main__":
    unittest.main()
