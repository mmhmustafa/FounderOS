"""Row selection: a select-all, and a click anywhere in the row.

Picking rows for a bulk action was pixel-hunting a 13px checkbox, and
with 21 folders to clear there was no way to say "all of them". The
behaviour is written once in atlas.js and adopted by attribute, so a
future bulk-action table inherits it — and the tests check the contract
both ways: the script implements it, and every selection table opts in.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest


STATIC = Path(__file__).resolve().parents[1] / "src/founderos_atlas/web/static"
TEMPLATES = (
    Path(__file__).resolve().parents[1] / "src/founderos_atlas/web/templates"
)

# Every table where rows are picked for a bulk action, and the checkbox
# name the server reads. Adding a bulk-action table means adding a line
# here — which is the point: the omission becomes a test failure.
SELECTION_TABLES = {
    "storage.html": "scope_id",
    "incidents.html": "case_ids",
    "policy.html": "subjects",
    "evidence_index.html": "device_ids",
}


class ScriptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (STATIC / "atlas.js").read_text(encoding="utf-8")

    def test_selection_is_wired_by_attribute_not_per_page(self) -> None:
        self.assertIn("table[data-row-select]", self.js)
        self.assertIn("data-select-all", self.js)

    def test_a_click_in_the_row_toggles_the_row(self) -> None:
        self.assertIn('closest("tbody tr")', self.js)

    def test_controls_inside_a_row_keep_their_own_behaviour(self) -> None:
        """A link opens, a button submits, the checkbox toggles itself —
        the row must not also fire and undo what was clicked."""

        match = re.search(r'closest\(\s*"a, button, input, select, textarea, label"',
                          self.js)
        self.assertIsNotNone(match, "row click must ignore interactive controls")

    def test_selecting_text_is_not_clicking_a_row(self) -> None:
        self.assertIn("getSelection", self.js)

    def test_partial_selection_is_shown_as_partial(self) -> None:
        """Neither on nor off. Without this, "select all" on a partly
        selected table looks like it did nothing."""

        self.assertIn("indeterminate", self.js)

    def test_toggling_a_row_dispatches_a_real_change_event(self) -> None:
        # Anything listening for a user's change must still hear it.
        self.assertIn('new Event("change", { bubbles: true })', self.js)

    def test_a_bulk_set_reads_the_wanted_value_once(self) -> None:
        """The bug this pins, found by clicking it in a browser while
        every static check passed: setting a box fires a bubbling
        change, which re-entered the header sync mid-loop and flipped
        master.checked to false after the FIRST box — so "select all"
        selected exactly one row and cleared the other twenty."""

        self.assertIn("var wanted = master.checked;", self.js)
        self.assertIn("bulkSetting = true;", self.js)
        self.assertIn("if (bulkSetting) { return; }", self.js)

    def test_the_count_is_found_outside_the_table(self) -> None:
        """It sits with the submit button, not in the table — looking
        only inside the table found nothing and the count stayed blank."""

        self.assertIn('table.closest("form") || document', self.js)

    def test_the_behaviour_is_not_nested_in_another_feature(self) -> None:
        """It was first appended to the end of the file, which is inside
        a block that returns early on any page without a
        <details data-remember>. The storage page has none, so the code
        never ran at all."""

        tail = self.js.split("-- Row selection")[1]
        # Nothing between the section start and its IIFE may be an early
        # return belonging to someone else's feature.
        self.assertNotIn("details[data-remember]", tail)
        self.assertIn("(function rowSelection() {", tail)

    def test_the_affordance_is_styled(self) -> None:
        css = (STATIC / "atlas.css").read_text(encoding="utf-8")
        self.assertIn("table[data-row-select] tbody tr { cursor: pointer; }", css)
        self.assertIn("row-selected", css)


class TemplateAdoptionTests(unittest.TestCase):
    def test_every_selection_table_opts_in(self) -> None:
        for name, field in SELECTION_TABLES.items():
            body = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn(
                f'data-row-select="{field}"', body,
                f"{name} has row checkboxes but does not opt into selection",
            )

    def test_every_selection_table_offers_select_all(self) -> None:
        for name in SELECTION_TABLES:
            body = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn(
                "data-select-all", body, f"{name} has no select-all control",
            )

    def test_select_all_controls_are_labelled(self) -> None:
        """A bare checkbox in a header reads as nothing to a screen
        reader."""

        for name in SELECTION_TABLES:
            body = (TEMPLATES / name).read_text(encoding="utf-8")
            for match in re.finditer(r"<input[^>]*data-select-all[^>]*>", body):
                self.assertIn(
                    "aria-label", match.group(0),
                    f"{name}: select-all needs an aria-label",
                )

    def test_the_declared_field_is_the_one_the_rows_use(self) -> None:
        """A mismatch would silently select nothing — the wiring names
        the checkbox, so the names must agree."""

        for name, field in SELECTION_TABLES.items():
            body = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn(
                f'name="{field}"', body,
                f"{name} declares data-row-select={field} but no row uses it",
            )

    def test_no_selection_table_was_missed(self) -> None:
        """Finds row-selection tables that never adopted the behaviour:
        a checkbox repeated inside a {% for %} loop is a bulk-action
        list, whatever page it lives on."""

        missed = []
        for path in sorted(TEMPLATES.glob("*.html")):
            body = path.read_text(encoding="utf-8")
            if path.name in SELECTION_TABLES:
                continue
            for match in re.finditer(
                r'<td[^>]*>\s*<input type="checkbox" name="([a-z_]+)"', body
            ):
                missed.append(f"{path.name}: {match.group(1)}")
        self.assertEqual(
            [], missed,
            "these tables select rows but are not in SELECTION_TABLES",
        )


if __name__ == "__main__":
    unittest.main()
