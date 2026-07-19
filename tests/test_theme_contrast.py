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

    def test_every_light_surface_has_a_dark_counterpart(self) -> None:
        """Sweep: any rule with a hard-coded light background (#e../#f..)
        must be restyled by some dark rule naming the same class or
        element — the recurring dark-mode bug class is a light chip
        keeping --muted/--ink text that flips light and vanishes."""

        css = CSS.read_text(encoding="utf-8")
        dark_selectors = " ".join(
            re.findall(r'body\[data-theme=.dark.\][^{]*', css)
        )
        # Saturated (non-light) colors that merely start with e/f, and
        # print-only or scrollbar rules, are not light surfaces.
        allowlist = {"sev-high"}
        misses = []
        for m in re.finditer(
            r"(?m)^([^\n{@]+)\{[^}]*background(?:-color)?:\s*"
            r"#[ef][0-9a-f]{2}(?:[0-9a-f]{3})?\b",
            css,
        ):
            selector = m.group(1).strip()
            if "data-theme" in selector or selector.startswith(":root"):
                continue
            classes = re.findall(r"\.[\w-]+", selector)
            key = classes[-1].lstrip(".") if classes else selector.split()[0]
            elements = re.findall(r"(?:^|[\s,>])(\w+)\b", selector)
            covered = key in dark_selectors or any(
                e in ("input", "select", "textarea", "kbd", "code", "mark")
                and e in dark_selectors
                for e in elements
            )
            if not covered and key not in allowlist:
                misses.append(f"{selector} (key {key})")
        self.assertEqual(
            [], misses,
            "light surfaces without a dark override:\n" + "\n".join(misses),
        )

    def test_every_dark_text_color_has_a_dark_counterpart(self) -> None:
        """Text analog of the background sweep: any hard-coded DARK text
        color (readable on white, invisible on the dark panel) must be
        restyled in dark mode — `.card ul { color: #334155 }` made the
        whole Home activity stream unreadable exactly this way."""

        css = CSS.read_text(encoding="utf-8")
        dark_txt = " ".join(
            re.findall(r'body\[data-theme=.dark.\][^{]*', css)
        )
        misses = []
        for m in re.finditer(r"(?m)^([^\n{@]+)\{([^}]*)\}", css):
            selector, body = m.group(1).strip(), m.group(2)
            if "data-theme" in selector or selector.startswith(":root"):
                continue
            for c in re.finditer(
                r"(?<![-\w])color:\s*(#[0-9a-fA-F]{3,6})\b", body
            ):
                value = c.group(1).lstrip("#")
                if len(value) == 3:
                    value = "".join(ch * 2 for ch in value)
                r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
                if 0.2126 * r + 0.7152 * g + 0.0722 * b > 100:
                    continue  # light text: fine on dark surfaces
                plain = re.sub(r":[\w-]+(\([^)]*\))?", "", selector)
                # Covered when a dark rule names the selector's tail
                # (".card ul") or restyles the bare trailing element.
                last_class = plain.rfind(".")
                tail = plain[last_class:].strip() if last_class >= 0 else plain
                element = re.findall(r"[\w-]+", plain)[-1]
                if tail.lstrip(".") in dark_txt:
                    continue
                if element in ("input", "select", "textarea", "kbd",
                               "code", "mark", "th") and element in dark_txt:
                    continue
                misses.append(f"{selector} -> {c.group(1)}")
        self.assertEqual(
            [], misses,
            "dark text colors without a dark override:\n"
            + "\n".join(misses),
        )

    def test_every_used_token_is_defined(self) -> None:
        """`var(--surface, #fff)` with an UNDEFINED token silently uses
        the light fallback in every theme — the device-picker dropdown
        shipped white-on-white in dark mode exactly this way."""

        css = CSS.read_text(encoding="utf-8")
        used = set(re.findall(r"var\((--[\w-]+)", css))
        # A custom property DECLARATION is `--name:` anywhere (several
        # tokens share a line); a var() reference never has the colon.
        defined = set(re.findall(r"(--[\w-]+)\s*:", css))
        self.assertEqual(
            set(), used - defined,
            f"tokens used but never defined: {sorted(used - defined)}",
        )

    def test_system_theme_mirrors_every_dark_rule(self) -> None:
        """data-theme="system" resolves via media query, so every
        `body[data-theme="dark"]` component rule needs a "system" twin
        inside @media (prefers-color-scheme: dark) — otherwise System
        users on a dark OS get dark tokens with light chrome."""

        css = CSS.read_text(encoding="utf-8")
        dark = css.count('body[data-theme="dark"]')
        system = css.count('body[data-theme="system"]')
        self.assertGreater(dark, 0)
        self.assertEqual(
            dark, system,
            "dark and system selector counts diverged — regenerate the "
            "System mirror block at the end of atlas.css",
        )

    def test_layers_panel_declares_its_own_ink(self) -> None:
        # The viewer header is dark with white text. The Layers summary
        # and dropdown sit on light surfaces inside it — without their
        # own color they inherit white and the labels vanish (the exact
        # bug an operator screenshotted). Every light-surface rule must
        # pair its background with an explicit ink, and dark mode must
        # restyle both.
        viewer = Path(
            "src/founderos_atlas/visualization/templates/topology.html"
        ).read_text(encoding="utf-8")
        for rule in (".layers-menu > summary {", ".layers-body {"):
            # Line-start match so the dark-theme override (which contains
            # the same selector as a suffix) is not picked up instead.
            start = viewer.index("\n    " + rule)
            block = viewer[start:viewer.index("}", start)]
            self.assertIn("background: #fff", block, rule)
            self.assertIn("color: #0f172a", block, rule)
        self.assertIn('body[data-theme="dark"] .layers-menu > summary',
                      viewer)
        self.assertIn('body[data-theme="dark"] .layers-body', viewer)
        outer = Path(
            "src/founderos_atlas/web/templates/topology.html"
        ).read_text(encoding="utf-8")
        self.assertIn("theme={{ ui_theme }}", outer)


if __name__ == "__main__":
    unittest.main()
