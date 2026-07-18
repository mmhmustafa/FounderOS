"""Every page renders the workflow sidebar.

Regression: /users, /inbox, and /system/integrity once rendered with an
EMPTY left navigation pane because their render calls (ops.py) never
passed the base context that carries ``nav_groups``. An app-wide
context processor now supplies navigation defaults, so a page can no
longer lose its shell by forgetting one keyword argument.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world

PAGES = (
    "/", "/topology", "/profiles", "/profiles/new", "/credentials",
    "/discovery", "/discovery/wizard", "/history", "/evidence",
    "/configuration", "/policy", "/changes", "/timeline", "/audit",
    "/incidents", "/paths", "/predict", "/compass", "/advisor",
    "/inbox", "/users", "/settings", "/settings/retention",
    "/system/update", "/system/integrity", "/console",
)


class NavigationShellTests(unittest.TestCase):
    def test_every_page_renders_the_sidebar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for page in PAGES:
                with self.subTest(page=page):
                    response = client.get(page, follow_redirects=True)
                    self.assertEqual(200, response.status_code)
                    html = response.get_data(as_text=True)
                    self.assertIn(
                        'class="nav-group', html,
                        f"{page} rendered without the workflow sidebar",
                    )

    def test_fixed_pages_highlight_their_workflow_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for page, group in (
                ("/users", "setup"),
                ("/inbox", "mission"),
                ("/system/integrity", "setup"),
            ):
                with self.subTest(page=page):
                    html = client.get(page).get_data(as_text=True)
                    self.assertIn("nav-group-current", html)


if __name__ == "__main__":
    unittest.main()
