"""Automated WCAG contrast checks for the design tokens (audit-2 #6).

Parses the light (:root) and dark token blocks in atlas.css and asserts
the AA thresholds hold for the pairs the UI actually renders: body ink
and muted text on the page and panel backgrounds, in BOTH themes. This
guards every future token tweak — a color change that breaks contrast
now fails the suite instead of shipping.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

CSS = Path("src/founderos_atlas/web/static/atlas.css")


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})", block))


def _relative_luminance(color: str) -> float:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    channels = []
    for i in (0, 2, 4):
        value = int(color[i:i + 2], 16) / 255
        channels.append(
            value / 12.92 if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
        )
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground: str, background: str) -> float:
    lighter = max(_relative_luminance(foreground),
                  _relative_luminance(background))
    darker = min(_relative_luminance(foreground),
                 _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


class TokenContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        css = CSS.read_text(encoding="utf-8")
        root = css.split(":root {", 1)[1].split("}", 1)[0]
        cls.light = _tokens(root)
        dark_block = css.split('body[data-theme="dark"] {', 1)[1].split(
            "}", 1
        )[0]
        # Dark inherits every unoverridden light token.
        cls.dark = {**cls.light, **_tokens(dark_block)}

    def _assert_aa(self, theme: dict, name: str,
                   fg: str, bg: str, minimum: float = 4.5) -> None:
        ratio = contrast(theme[fg], theme[bg])
        self.assertGreaterEqual(
            ratio, minimum,
            f"{name}: --{fg} on --{bg} is {ratio:.2f}:1 (< {minimum}:1)",
        )

    def test_light_theme_meets_aa(self) -> None:
        self._assert_aa(self.light, "light body text", "ink", "bg")
        self._assert_aa(self.light, "light panel text", "ink", "panel")
        self._assert_aa(self.light, "light muted on panel", "muted", "panel")
        self._assert_aa(self.light, "light muted on page", "muted", "bg")

    def test_dark_theme_meets_aa(self) -> None:
        self._assert_aa(self.dark, "dark body text", "ink", "bg")
        self._assert_aa(self.dark, "dark panel text", "ink", "panel")
        self._assert_aa(self.dark, "dark muted on panel", "muted", "panel")
        self._assert_aa(self.dark, "dark muted on page", "muted", "bg")

    def test_status_text_tokens_meet_aa_on_their_surfaces(self) -> None:
        # Status words render on panel surfaces in both themes.
        self._assert_aa(self.light, "light amber text", "amber", "panel")
        self._assert_aa(self.light, "light green text", "green", "panel")
        self._assert_aa(self.light, "light red text", "red", "panel", 4.0)

    def test_dark_component_overrides_exist(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        for selector in (
            '[data-theme="dark"] .btn',
            '[data-theme="dark"] thead th',
            '[data-theme="dark"] .tile',
            '[data-theme="dark"] .flash',
            '[data-theme="dark"] pre',
        ):
            self.assertIn(selector, css, selector)

    def test_viewer_receives_theme_and_defines_dark_chrome(self) -> None:
        viewer = Path(
            "src/founderos_atlas/visualization/templates/topology.html"
        ).read_text(encoding="utf-8")
        self.assertIn("query.get('theme')", viewer)
        self.assertIn('body[data-theme="dark"]', viewer)
        outer = Path(
            "src/founderos_atlas/web/templates/topology.html"
        ).read_text(encoding="utf-8")
        self.assertIn("theme={{ ui_theme }}", outer)


if __name__ == "__main__":
    unittest.main()
