"""The hidden attribute must always win (UI contract).

Any author ``display`` declaration (``.btn { display: inline-flex }``)
silently defeats the user-agent's ``[hidden] { display: none }`` rule —
the Discovery Wizard's Continue button stayed painted on the Preview
step exactly this way, surviving a correct ``next.hidden = true``. The
stylesheet carries one global ``[hidden]`` guard so hidden means gone
for every current and future element.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

CSS = Path("src/founderos_atlas/web/static/atlas.css")


class HiddenAttributeTests(unittest.TestCase):
    def test_global_hidden_guard_exists_and_is_important(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        self.assertRegex(
            css,
            r"(?m)^\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}",
            "atlas.css must carry the global [hidden] guard",
        )

    def test_guard_precedes_every_display_declaration(self) -> None:
        # The guard must be declared before any rule that could contest
        # it, so a reader auditing the cascade sees the contract first.
        css = re.sub(
            r"/\*.*?\*/", lambda m: " " * len(m.group(0)),
            CSS.read_text(encoding="utf-8"), flags=re.DOTALL,
        )
        guard = css.index("[hidden] { display: none !important; }")
        first_display = re.search(r"\.[\w-]+[^{]*\{[^}]*display:", css)
        self.assertIsNotNone(first_display)
        self.assertLess(guard, first_display.start())


if __name__ == "__main__":
    unittest.main()
