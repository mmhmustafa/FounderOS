"""Breadth regression for table simplification (audit-2 #4).

Every major high-density table must carry the column-customization
contract: a stable ``data-columns`` id, ``data-col`` headers with
Simple/Detailed/Expert presets, and an accessible name for every
column whose visible heading is blank (action/select columns). The
engine itself must hide by column position (thead-only adoption),
never write a preference on initial page load, and label toggles
from ``data-col-label`` — never from whitespace headings.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATES = Path("src/founderos_atlas/web/templates")
ATLAS_JS = Path("src/founderos_atlas/web/static/atlas.js")

# template file -> stable table ids expected inside it
ADOPTED = {
    "audit.html": ["audit-events"],
    "users.html": ["users"],
    "history.html": ["discoveries"],
    "changes.html": ["changes"],
    "incidents.html": ["incidents"],
    "configuration.html": ["config-devices"],
    "credentials.html": ["credentials"],
    "profiles.html": ["profiles"],
    "paths.html": ["path-history"],
    "predict.html": ["predictions"],
    "compass.html": ["compass-plans"],
    "retention.html": ["retention-preview"],
    "inbox.html": ["inbox"],
    "policy.html": ["policy-results", "policy-packs"],
    "evidence_index.html": ["evidence-devices"],
}


def _tables(html: str):
    """Yield (data_columns_name, thead_html) for adopted tables."""
    for match in re.finditer(
        r'<table[^>]*data-columns="([^"]+)"[^>]*>(.*?)</thead>',
        html,
        re.DOTALL,
    ):
        yield match.group(1), match.group(2)


class AdoptionBreadthTests(unittest.TestCase):
    def test_every_major_table_is_adopted(self) -> None:
        for template, names in ADOPTED.items():
            html = (TEMPLATES / template).read_text(encoding="utf-8")
            found = [name for name, _ in _tables(html)]
            for name in names:
                self.assertIn(
                    name, found,
                    f"{template}: table data-columns={name!r} missing",
                )

    def test_adopted_headers_carry_col_ids_and_presets(self) -> None:
        valid_presets = {"simple", "detailed", "expert"}
        for template, names in ADOPTED.items():
            html = (TEMPLATES / template).read_text(encoding="utf-8")
            for name, thead in _tables(html):
                if name not in names:
                    continue
                headers = re.findall(r"<th\b[^>]*>", thead)
                self.assertTrue(headers, f"{template}/{name}: no headers")
                for th in headers:
                    self.assertIn(
                        "data-col=", th,
                        f"{template}/{name}: header without data-col: {th}",
                    )
                    preset = re.search(r'data-col-preset="([^"]+)"', th)
                    if preset:
                        self.assertIn(preset.group(1), valid_presets, th)
                # At least one column stays in the Simple preset so the
                # table can never collapse to nothing.
                self.assertIn('data-col-preset="simple"', thead,
                              f"{template}/{name}")

    def test_blank_headings_have_accessible_toggle_names(self) -> None:
        for template, names in ADOPTED.items():
            html = (TEMPLATES / template).read_text(encoding="utf-8")
            for name, thead in _tables(html):
                if name not in names:
                    continue
                for th, body in re.findall(
                    r"(<th\b[^>]*>)((?:(?!</th>).)*)</th>", thead, re.DOTALL
                ):
                    visible = re.sub(r"<[^>]+>", "", body)
                    visible = re.sub(r"{{.*?}}|{%.*?%}", "x", visible)
                    if visible.strip():
                        continue  # visible heading names the toggle
                    self.assertIn(
                        "data-col-label=", th,
                        f"{template}/{name}: blank heading without "
                        f"data-col-label: {th}{body}</th>",
                    )

    def test_engine_hides_by_position_and_never_saves_on_load(self) -> None:
        js = ATLAS_JS.read_text(encoding="utf-8")
        # Thead-only adoption: body cells hide by column index.
        self.assertIn("row.children[index]", js)
        # Rows using colspans (detail/empty rows) keep their layout.
        self.assertIn("row.children.length !== allHead.length", js)
        # Initial presets are views, not choices: all three page-load
        # fallbacks pass save=false. (The Reset button also applies the
        # level preset but IS a user action, so it persists — that call
        # site legitimately omits the flag.)
        self.assertEqual(
            js.count('applyPreset(document.body.dataset.displayLevel'
                     ' || "detailed", false)'),
            3,
            "the three restore fallbacks must not persist",
        )
        # Toggle labels never come from whitespace headings.
        self.assertIn("th.dataset.colLabel", js)
        # A refused save is reported, not swallowed.
        self.assertIn("Column choice was not saved", js)


class FilterDisclosureTests(unittest.TestCase):
    """Filter bars collapse at Simple, open at Detailed/Expert (#3).

    The form is always rendered — a collapsed native <details> hides
    nothing from keyboard or no-JS users, and GET filter URLs keep
    working unchanged.
    """

    WRAPPED = ["audit.html", "changes.html", "incidents.html",
               "paths.html", "policy.html", "timeline.html"]

    def test_filter_bars_sit_in_level_aware_disclosures(self) -> None:
        for template in self.WRAPPED:
            html = (TEMPLATES / template).read_text(encoding="utf-8")
            self.assertIn(
                'disclosure-filters" '
                "{{ 'open' if display_level != 'simple' else '' }}",
                html, template,
            )

    def test_action_forms_are_never_behind_a_filters_summary(self) -> None:
        # POST forms (rename, assign, acknowledge) must stay directly
        # reachable; only GET filter forms may collapse.
        for path in TEMPLATES.glob("*.html"):
            html = path.read_text(encoding="utf-8")
            for m in re.finditer(
                r'<details class="disclosure disclosure-filters"'
                r".*?(<form\b[^>]*>)", html, re.DOTALL,
            ):
                self.assertNotIn(
                    'method="post"', m.group(1),
                    f"{path.name}: POST form wrapped in filter disclosure",
                )


if __name__ == "__main__":
    unittest.main()
