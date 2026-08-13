"""PR-178.1 capability-preservation gate, against rendered pages.

Retiring the inline device_actions buttons from Evidence and
Configuration TABLE ROWS is allowed ONLY because every removed control
has a named survivor in the same row's menu. This file is that matrix,
row by row:

    Open SSH Console        -> menu: "Open SSH console to {device}"
    Copy SSH Command        -> menu: "Copy SSH command for {device}"
    Open HTTPS (+cert flag) -> menu web group: "Open HTTPS"
    Copy HTTPS URL          -> menu web group: "Copy HTTPS URL"
    Open HTTP — Insecure    -> menu web group: "Open HTTP — Insecure"
    Copy HTTP URL           -> menu web group: "Copy HTTP URL"
    Web unavailable+reason  -> menu web group: greyed item + reason
    SSH unavailable+reason  -> menu: existing greyed ssh treatment

Configuration / Investigate / Predict were NOT emitted by compact
device_actions in rows (they render only when ``not compact``), so there
is no preservation work for them — asserting otherwise would be fake
coverage. Detail pages keep the inline buttons and are asserted
unchanged elsewhere (test_row_action_menus.RowMigrationTests).
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from tests.test_polish import build_world


def _first_evidence_device_ids(page: bytes) -> list[str]:
    """Canonical memory device ids, scraped from the rendered rows."""

    found = []
    for match in re.finditer(rb'href="/evidence/device/([^"?]+)', page):
        device_id = unquote(match.group(1).decode("ascii"))
        if device_id not in found:
            found.append(device_id)
    return found


class RowCapabilityPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.workdir = Path(cls._tmp.name)
        _, cls.client = build_world(cls.workdir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- the rows read as data ---------------------------------------------

    def test_no_accent_console_buttons_remain_in_evidence_rows(self) -> None:
        page = self.client.get("/evidence?scope=hyderabad").data
        self.assertNotIn(b"btn-console", page)
        self.assertNotIn(b"device-actions-compact", page)

    # -- and every removed control has its named survivor -------------------

    def test_ssh_actions_survive_into_the_evidence_row_menu(self) -> None:
        page = self.client.get("/evidence?scope=hyderabad").data
        self.assertIn(b"Open SSH console to", page)
        self.assertIn(b"js-copy-ssh", page)
        self.assertIn(b"data-ssh-command", page)
        self.assertIn(b'href="/console/', page)

    def test_the_web_question_is_answered_in_every_evidence_row_menu(self) -> None:
        """No services are recorded in this world, so the answer must be
        the greyed item WITH its reason — an empty cell would read as
        "Atlas didn't check"."""

        page = self.client.get("/evidence?scope=hyderabad").data
        self.assertIn(b"Open web interface", page)
        # The macro's disabled branch always carries the reason.
        self.assertIn(b"\xe2\x80\x94 unavailable:", page)

    def test_the_primary_evidence_row_link_is_unchanged(self) -> None:
        evidence = self.client.get("/evidence?scope=hyderabad").data
        self.assertIn(b'href="/evidence/device/', evidence)

    def test_verified_https_and_http_branches_survive_exactly(self) -> None:
        """Seed one HTTPS endpoint and one HTTP-only endpoint the way an
        operator would, then read the menus: open+copy for each protocol,
        with the exact insecure wording and the audit wiring intact."""

        from founderos_atlas.management import ManagementServiceStore
        from founderos_atlas.workspace import profile_scope

        page = self.client.get("/evidence?scope=hyderabad").data
        device_ids = _first_evidence_device_ids(page)
        self.assertGreaterEqual(
            len(device_ids), 2, "world must offer two devices to seed"
        )
        https_device, http_device = device_ids[0], device_ids[1]
        scope = profile_scope(self.workdir, "hyderabad", "Hyderabad")
        store = ManagementServiceStore(
            scope.output_dir / "management-services.json"
        )
        store.define_endpoint(
            https_device, url="https://10.0.9.9:8443", protocol="https",
            address="10.0.9.9", port=8443, user="netops",
        )
        store.define_endpoint(
            http_device, url="http://10.0.9.8", protocol="http",
            address="10.0.9.8", port=80, user="netops",
        )
        try:
            page = self.client.get("/evidence?scope=hyderabad").data
            # HTTPS: open (new tab, audited) + copy.
            self.assertIn(b">Open HTTPS", page)
            self.assertIn(b"js-web-open", page)
            self.assertIn(b'data-protocol="https"', page)
            self.assertIn(b"Copy HTTPS URL", page)
            self.assertIn(b"https://10.0.9.9:8443", page)
            # HTTP-only: the exact insecure wording + confirm wiring.
            self.assertIn("Open HTTP — Insecure".encode("utf-8"), page)
            self.assertIn(b"js-web-open-insecure", page)
            self.assertIn(b"Copy HTTP URL", page)
            self.assertIn(b"http://10.0.9.8", page)
            self.assertIn(b"js-copy-url", page)
        finally:
            store.clear_override(https_device, "https://10.0.9.9:8443")
            store.clear_override(http_device, "http://10.0.9.8")

class ConfigurationRowCapabilityTests(unittest.TestCase):
    """The same matrix for Configuration rows. The bare world's
    configuration memory is empty, so this class seeds one configured
    device (GW, the shared gateway) exactly the way the navigation
    workflow tests do."""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.test_navigation import seed_policy_memory

        cls._tmp = tempfile.TemporaryDirectory()
        cls.workdir = Path(cls._tmp.name)
        _, cls.client = build_world(cls.workdir)
        cls.device_id, _ = seed_policy_memory(cls.workdir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_configuration_rows_read_as_data_with_the_shared_menu(self) -> None:
        page = self.client.get("/configuration?scope=hyderabad").data
        self.assertIn(b">Open configuration</a>", page)
        self.assertNotIn(b"btn-console", page)
        self.assertNotIn(b"device-actions-compact", page)
        self.assertIn(b"action-menu", page)

    def test_ssh_and_web_survive_into_the_configuration_row_menu(self) -> None:
        page = self.client.get("/configuration?scope=hyderabad").data
        # GW is an eligible console target in this world, so the live SSH
        # actions must both survive; web is unverified, so the greyed
        # item must carry its reason.
        self.assertIn(b"Open SSH console to", page)
        self.assertIn(b"js-copy-ssh", page)
        self.assertIn(b"Open web interface", page)
        self.assertIn(b"\xe2\x80\x94 unavailable:", page)

    def test_a_device_with_versions_keeps_a_live_configuration_link(self) -> None:
        """has_configuration is passed from the store's own version
        count — an ESTABLISHED fact, so the menu's Configuration entry
        stays live for stored devices."""

        page = self.client.get("/configuration?scope=hyderabad").data
        self.assertIn(b"Configuration of", page)
        self.assertNotIn(
            b"no configuration is held", page,
            "a stored device must not be told it has no configuration",
        )


class BoundedBackendWorkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.workdir = Path(cls._tmp.name)
        _, cls.client = build_world(cls.workdir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- no new per-device backend work --------------------------------------

    def test_menu_pages_parse_the_services_file_once_per_scope(self) -> None:
        """The web group must reuse the per-request cache + the memoised
        store read: one parse per scope per request, NEVER one per device
        (the pre-PR-178.1 cost was 85 parses per Evidence render)."""

        from founderos_atlas.management.store import ManagementServiceStore

        counts = {"loads": 0}
        original = ManagementServiceStore._load

        def counting(self):
            counts["loads"] += 1
            return original(self)

        ManagementServiceStore._load = counting
        try:
            for path in (
                "/evidence?scope=hyderabad", "/configuration?scope=hyderabad",
                "/policy?scope=hyderabad", "/timeline?scope=hyderabad",
                "/topology?scope=hyderabad",
            ):
                counts["loads"] = 0
                response = self.client.get(path)
                self.assertEqual(200, response.status_code, path)
                self.assertLessEqual(
                    counts["loads"], 2,
                    f"{path}: {counts['loads']} parses — the memo is not working",
                )
        finally:
            ManagementServiceStore._load = original


if __name__ == "__main__":
    unittest.main()
