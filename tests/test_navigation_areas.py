"""Five-area navigation (PR: calmer navigation).

One primary area open at a time via native details/summary (no JS
needed for basic navigation), the active area opened server-side,
RBAC-filtered items, and an inbox count that stays a count — not a
dashboard.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world
from tests.test_production_security import production_world, sign_in


class AccordionTests(unittest.TestCase):
    def test_only_the_active_area_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/policy").get_data(as_text=True)
            details = re.findall(r'<details class="nav-details" ?(open)?>', page)
            self.assertEqual(5, len(details))
            self.assertEqual(1, sum(1 for open_ in details if open_))
            # Policy lives under Operations — that is the open area.
            open_block = page.split('<details class="nav-details" open>')[1]
            self.assertIn("Operations", open_block.split("</details>")[0])

    def test_every_destination_stays_one_click_deep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/").get_data(as_text=True)
            for href in ("/", "/inbox", "/incidents", "/topology",
                         "/configuration", "/evidence", "/timeline",
                         "/history", "/changes", "/policy", "/advisor",
                         "/paths", "/predict", "/compass", "/discovery",
                         "/profiles", "/credentials", "/users", "/audit",
                         "/settings"):
                self.assertIn(f'href="{href}"', page, href)

    def test_deep_links_open_their_own_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for path, area in (
                ("/credentials", "Administration"),
                ("/evidence", "Network"),
                ("/inbox", "Home"),
                ("/compass", "Analyze"),
            ):
                page = client.get(path).get_data(as_text=True)
                open_block = page.split(
                    '<details class="nav-details" open>'
                )[1].split("</details>")[0]
                self.assertIn(area, open_block, path)


class RbacFilteringTests(unittest.TestCase):
    def test_viewer_sidebar_omits_unauthorized_admin_items(self) -> None:
        with production_world() as (app, _):
            viewer, _csrf = sign_in(app, "viewer")
            page = viewer.get("/").get_data(as_text=True)
            sidebar = page.split('id="atlas-sidebar"')[1].split("</nav>")[0]
            # What a viewer cannot open is not advertised…
            self.assertNotIn('href="/users"', sidebar)
            # …what they can open stays.
            self.assertIn('href="/settings"', sidebar)
            self.assertIn('href="/topology"', sidebar)

    def test_admin_sidebar_shows_administration_in_full(self) -> None:
        with production_world() as (app, _):
            admin, _csrf = sign_in(app, "admin")
            sidebar = (
                admin.get("/").get_data(as_text=True)
                .split('id="atlas-sidebar"')[1].split("</nav>")[0]
            )
            for href in ("/users", "/credentials", "/profiles", "/audit"):
                self.assertIn(f'href="{href}"', sidebar)

    def test_filtering_never_replaces_enforcement(self) -> None:
        with production_world() as (app, _):
            viewer, _csrf = sign_in(app, "viewer")
            # Hidden from the sidebar AND still denied on direct access.
            self.assertEqual(403, viewer.get("/users").status_code)


class LocalModeTests(unittest.TestCase):
    def test_local_mode_shows_every_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/").get_data(as_text=True)
            for label in ("Home", "Network", "Operations", "Analyze",
                          "Administration"):
                self.assertIn(label, page)


if __name__ == "__main__":
    unittest.main()
