"""Change annotation identity & scope isolation (PR-178.2A).

The defect this pins shut, measured in the architecture review: the
change subject was the content hash alone, so the identical delta in
two independent networks was ONE annotatable record — acknowledging it
in Hyderabad silently acknowledged it in Secunderabad, and suppressing
it hid evidence in scopes nobody chose.

The contract now: identity = the observation point that reported the
change plus the exact difference it reported
(``change:v2:<scope_id>:<content-hash>``). Writes are always scoped.
Pre-isolation records stay readable through ONE canonical read-only
fallback and decay per scope the first time an operator acts there.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


ROW = {
    "kind": "topology", "category": "neighbor", "device": "R1",
    "field": "bgp-neighbor", "before": "Established", "after": "Idle",
    "description": "R1 BGP neighbour went to Idle",
}

REPORT = {
    "generated_at": "2026-08-13T01:00:00+00:00",
    "changes": [
        {"category": "neighbor", "severity": "high", "subject": "R1",
         "field": "bgp-neighbor", "previous_value": "Established",
         "current_value": "Idle",
         "description": "R1 BGP neighbour went to Idle"},
    ],
}


def _report_with(extra_changes) -> dict:
    return {
        "generated_at": REPORT["generated_at"],
        "changes": list(REPORT["changes"]) + list(extra_changes),
    }


class IdentityContractTests(unittest.TestCase):
    """Pure-function contract: durability kept, isolation added."""

    def test_same_scope_same_content_is_the_same_subject(self) -> None:
        """Rediscovery durability — the property v1 got right survives."""

        from founderos_atlas.change.identity import subject_v2

        self.assertEqual(
            subject_v2(ROW, "hyderabad"), subject_v2(dict(ROW), "hyderabad")
        )

    def test_different_scopes_are_different_subjects(self) -> None:
        from founderos_atlas.change.identity import subject_v2

        self.assertNotEqual(
            subject_v2(ROW, "hyderabad"), subject_v2(ROW, "secunderabad")
        )

    def test_different_content_is_a_different_subject(self) -> None:
        """A recurring-but-changed delta is never pre-acknowledged."""

        from founderos_atlas.change.identity import subject_v2

        recurred = dict(ROW, before="Idle", after="Established")
        self.assertNotEqual(
            subject_v2(ROW, "hyderabad"), subject_v2(recurred, "hyderabad")
        )

    def test_identity_ignores_the_display_label_and_timestamps(self) -> None:
        """Renaming a profile changes its label, never its id — so the
        hash must not consume network/occurred_at at all."""

        from founderos_atlas.change.identity import subject_v2

        renamed = dict(ROW, network="Hyderabad Production",
                       occurred_at="2027-01-01T00:00:00+00:00")
        self.assertEqual(
            subject_v2(ROW, "hyderabad"), subject_v2(renamed, "hyderabad")
        )

    def test_the_content_basis_is_exactly_the_v1_basis(self) -> None:
        """The v2 hash and the legacy fingerprint must agree, or the
        migration could never match a legacy record to its row."""

        from founderos_atlas.change.explorer import change_fingerprint
        from founderos_atlas.change.identity import (
            content_hash, subject_v1,
        )

        self.assertEqual("change:" + content_hash(ROW), subject_v1(ROW))
        self.assertEqual(change_fingerprint(ROW), subject_v1(ROW))

    def test_subject_format_and_parser_roundtrip(self) -> None:
        from founderos_atlas.change.identity import (
            legacy_subject_of, parse_v2, scope_of, subject_v2,
        )

        subject = subject_v2(ROW, "hyderabad")
        self.assertTrue(subject.startswith("change:v2:hyderabad:"))
        scope, digest = parse_v2(subject)
        self.assertEqual("hyderabad", scope)
        self.assertEqual(20, len(digest))
        self.assertEqual("hyderabad", scope_of(subject))
        self.assertEqual("change:" + digest, legacy_subject_of(subject))
        # Legacy and malformed ids parse to None — never a guess.
        self.assertIsNone(parse_v2("change:" + digest))
        self.assertIsNone(parse_v2("change:v2:"))
        self.assertIsNone(scope_of("policy-result:X:host"))

    def test_a_v2_subject_requires_a_scope(self) -> None:
        from founderos_atlas.change.identity import subject_v2

        with self.assertRaises(ValueError):
            subject_v2(ROW, "")


class ResolverTests(unittest.TestCase):
    """One canonical precedence: scoped record wins, legacy is read-only
    display fallback."""

    def test_v2_wins_over_v1(self) -> None:
        from founderos_atlas.change.identity import resolve_annotation

        records = {
            "change:v2:hyderabad:abc": {"owner": "scoped"},
            "change:abc": {"owner": "legacy"},
        }
        found = resolve_annotation(records, "change:v2:hyderabad:abc",
                                   "change:abc")
        self.assertEqual("scoped", found["owner"])

    def test_v1_serves_when_no_scoped_record_exists(self) -> None:
        from founderos_atlas.change.identity import resolve_annotation

        records = {"change:abc": {"owner": "legacy"}}
        found = resolve_annotation(records, "change:v2:hyderabad:abc",
                                   "change:abc")
        self.assertEqual("legacy", found["owner"])

    def test_nothing_matches_nothing(self) -> None:
        from founderos_atlas.change.identity import resolve_annotation

        self.assertIsNone(resolve_annotation({}, "change:v2:h:abc", "change:abc"))
        self.assertIsNone(resolve_annotation(None, "change:v2:h:abc", None))


class RowIdentityTests(unittest.TestCase):
    def test_rows_carry_scoped_subject_and_legacy_twin(self) -> None:
        from founderos_atlas.change.explorer import unified_rows
        from founderos_atlas.change.identity import subject_v1

        rows = unified_rows(
            topology_report=REPORT, config_report=None, state_report=None,
            scope_id="hyderabad", network="Hyderabad",
        )
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertTrue(row["subject"].startswith("change:v2:hyderabad:"))
        self.assertEqual(subject_v1(row), row["subject_legacy"])
        self.assertEqual("hyderabad", row["scope_id"])

    def test_two_scopes_mint_two_subjects_for_one_delta(self) -> None:
        from founderos_atlas.change.explorer import unified_rows

        mint = lambda scope, label: unified_rows(
            topology_report=REPORT, config_report=None, state_report=None,
            scope_id=scope, network=label,
        )[0]["subject"]
        self.assertNotEqual(
            mint("hyderabad", "Hyderabad"),
            mint("secunderabad", "Secunderabad"),
        )


class AnnotateRowsSemanticsTests(unittest.TestCase):
    """Value semantics: presence still means what it always did, and a
    scoped negative shadows a read-only legacy record in its scope."""

    def _row(self):
        from founderos_atlas.change.explorer import unified_rows

        return unified_rows(
            topology_report=REPORT, config_report=None, state_report=None,
            scope_id="hyderabad", network="Hyderabad",
        )

    def test_legacy_record_displays_when_no_scoped_record_exists(self) -> None:
        from founderos_atlas.change.explorer import annotate_rows

        rows = self._row()
        legacy = rows[0]["subject_legacy"]
        out = annotate_rows(rows, acks={legacy: {"acknowledged": True}},
                            suppressions={legacy: {"reason": "planned"}})
        self.assertTrue(out[0]["acknowledged"])
        self.assertTrue(out[0]["suppressed"])
        self.assertEqual("planned", out[0]["suppression_reason"])

    def test_scoped_record_wins_over_legacy(self) -> None:
        from founderos_atlas.change.explorer import annotate_rows

        rows = self._row()
        subject, legacy = rows[0]["subject"], rows[0]["subject_legacy"]
        out = annotate_rows(
            rows,
            assignments={legacy: {"owner": "old-owner"},
                         subject: {"owner": "new-owner"}},
        )
        self.assertEqual("new-owner", out[0]["owner"])

    def test_a_scoped_negative_shadows_a_legacy_positive(self) -> None:
        """Un-acknowledging / un-suppressing a legacy-displayed state
        writes a scoped negative — this scope reads clean while the
        legacy record keeps serving every other scope."""

        from founderos_atlas.change.explorer import annotate_rows

        rows = self._row()
        subject, legacy = rows[0]["subject"], rows[0]["subject_legacy"]
        out = annotate_rows(
            rows,
            acks={legacy: {"acknowledged": True},
                  subject: {"acknowledged": False}},
            suppressions={legacy: {"reason": "planned"},
                          subject: {"suppressed": False}},
        )
        self.assertFalse(out[0]["acknowledged"])
        self.assertFalse(out[0]["suppressed"])
        self.assertEqual("", out[0]["suppression_reason"])


class CrossScopeIsolationTests(unittest.TestCase):
    """The rendered app, per annotation kind: act in scope A, scope B
    must be untouched — including when acting from Enterprise."""

    @classmethod
    def setUpClass(cls) -> None:
        from founderos_atlas.workspace import profile_scope

        cls._tmp = tempfile.TemporaryDirectory()
        cls.workdir = Path(cls._tmp.name)
        _, cls.client = build_world(cls.workdir)
        for profile_id in ("hyderabad", "secunderabad"):
            scope = profile_scope(cls.workdir, profile_id, profile_id.title())
            (scope.output_dir / "change_report.json").write_text(
                json.dumps(REPORT), encoding="utf-8"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _subjects(self, scope: str) -> list[str]:
        page = self.client.get(f"/changes?scope={scope}").data.decode("utf-8")
        return re.findall(r'<tr id="(change:[^"]+)"', page)

    def _row_state(self, scope: str, subject: str) -> str:
        page = self.client.get(
            f"/changes?scope={scope}&suppressed=1"
        ).data.decode("utf-8")
        match = re.search(
            r'<tr id="' + re.escape(subject) + r'".*?</tr>', page, re.DOTALL
        )
        return match.group(0) if match else ""

    def _annotate(self, scope: str, subject: str, action: str, **extra):
        data = {"action": action, "subject": subject,
                "next": f"/changes?scope={scope}", **extra}
        return self.client.post("/changes/annotate", data=data,
                                follow_redirects=True)

    def test_the_same_delta_renders_two_scoped_subjects(self) -> None:
        hyd, sec = self._subjects("hyderabad"), self._subjects("secunderabad")
        self.assertTrue(hyd[0].startswith("change:v2:hyderabad:"))
        self.assertTrue(sec[0].startswith("change:v2:secunderabad:"))
        self.assertNotEqual(hyd[0], sec[0])

    def test_enterprise_shows_both_rows_with_distinct_dom_ids(self) -> None:
        """The measured duplicate-DOM-id defect is gone: Enterprise is a
        view over scoped facts and mints no identity of its own."""

        subjects = self._subjects("all")
        self.assertEqual(len(subjects), len(set(subjects)),
                         f"duplicate DOM ids in Enterprise: {subjects}")
        self.assertTrue(any(":hyderabad:" in s for s in subjects))
        self.assertTrue(any(":secunderabad:" in s for s in subjects))

    def test_acknowledge_in_a_leaves_b_untouched(self) -> None:
        hyd = self._subjects("hyderabad")[0]
        sec = self._subjects("secunderabad")[0]
        self._annotate("hyderabad", hyd, "acknowledge")
        try:
            self.assertIn("acknowledged", self._row_state("hyderabad", hyd))
            self.assertNotIn("acknowledged", self._row_state("secunderabad", sec))
        finally:
            self._annotate("hyderabad", hyd, "unacknowledge")

    def test_assignment_in_a_leaves_b_untouched(self) -> None:
        hyd = self._subjects("hyderabad")[0]
        sec = self._subjects("secunderabad")[0]
        self._annotate("hyderabad", hyd, "assign", owner="ahmed")
        self.assertIn("ahmed", self._row_state("hyderabad", hyd))
        self.assertNotIn("ahmed", self._row_state("secunderabad", sec))

    def test_note_in_a_leaves_b_untouched(self) -> None:
        hyd = self._subjects("hyderabad")[0]
        sec = self._subjects("secunderabad")[0]
        self._annotate("hyderabad", hyd, "note", note="site-specific context")
        self.assertIn("site-specific context", self._row_state("hyderabad", hyd))
        self.assertNotIn("site-specific context",
                         self._row_state("secunderabad", sec))

    def test_suppression_in_a_leaves_b_untouched(self) -> None:
        hyd = self._subjects("hyderabad")[0]
        sec = self._subjects("secunderabad")[0]
        self._annotate("hyderabad", hyd, "suppress", reason="planned work")
        try:
            hyd_page = self.client.get(
                "/changes?scope=hyderabad"
            ).data.decode("utf-8")
            sec_page = self.client.get(
                "/changes?scope=secunderabad"
            ).data.decode("utf-8")
            self.assertIn("suppressed change(s) hidden", hyd_page)
            self.assertNotIn("suppressed change(s) hidden", sec_page)
            self.assertIn(sec, sec_page)
        finally:
            self._annotate("hyderabad", hyd, "unsuppress")

    def test_enterprise_action_touches_exactly_the_originating_scope(self) -> None:
        subjects = self._subjects("all")
        target = next(s for s in subjects if ":hyderabad:" in s)
        twin = next(s for s in subjects if ":secunderabad:" in s)
        self._annotate("all", target, "acknowledge")
        try:
            self.assertIn("acknowledged", self._row_state("hyderabad", target))
            self.assertNotIn("acknowledged",
                             self._row_state("secunderabad", twin))
            # And the audit event names the real scope, not "all".
            audit = json.loads(
                (self.workdir / "workspace" / "audit.jsonl")
                .read_text(encoding="utf-8").splitlines()[-1]
            )
            self.assertEqual("hyderabad", audit["scope_id"])
            self.assertEqual(target, audit["subject"])
        finally:
            self._annotate("all", target, "unacknowledge")

    def test_new_writes_never_use_v1_subjects(self) -> None:
        hyd = self._subjects("hyderabad")[0]
        self._annotate("hyderabad", hyd, "note", note="v2 only")
        annotations = json.loads(
            (self.workdir / "workspace" / "annotations.json")
            .read_text(encoding="utf-8")
        )["annotations"]
        for kind, records in annotations.items():
            if not kind.startswith("change-"):
                continue
            for subject in records:
                self.assertTrue(
                    subject.startswith("change:v2:"),
                    f"{kind} wrote a non-v2 subject: {subject}",
                )


class LegacyFallbackLifecycleTests(unittest.TestCase):
    """A pre-isolation record: displayed everywhere its content renders,
    never written through, shadowed per scope on the first action."""

    def setUp(self) -> None:
        from founderos_atlas.workspace import profile_scope

        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        _, self.client = build_world(self.workdir)
        for profile_id in ("hyderabad", "secunderabad"):
            scope = profile_scope(self.workdir, profile_id, profile_id.title())
            (scope.output_dir / "change_report.json").write_text(
                json.dumps(REPORT), encoding="utf-8"
            )
        # A legacy, scope-blind acknowledgement + suppression, written
        # exactly as the pre-PR-178.2A store did.
        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.change.identity import subject_v1

        report_row = {
            "kind": "topology", "category": "neighbor", "device": "R1",
            "field": "bgp-neighbor", "before": "Established", "after": "Idle",
            "description": "R1 BGP neighbour went to Idle",
        }
        self.legacy = subject_v1(report_row)
        store = AnnotationStore(self.workdir / "workspace")
        store.set(kind="change-ack", subject=self.legacy,
                  fields={"acknowledged": True}, actor="pre-isolation")
        store.set(kind="change-suppression", subject=self.legacy,
                  fields={"reason": "legacy suppression"},
                  actor="pre-isolation")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _annotations(self) -> dict:
        return json.loads(
            (self.workdir / "workspace" / "annotations.json")
            .read_text(encoding="utf-8")
        )["annotations"]

    def test_legacy_state_displays_in_every_scope_that_renders_it(self) -> None:
        for scope in ("hyderabad", "secunderabad"):
            page = self.client.get(
                f"/changes?scope={scope}&suppressed=1"
            ).data.decode("utf-8")
            self.assertIn("acknowledged", page)
            self.assertIn("legacy suppression", page)

    def test_reading_never_writes(self) -> None:
        before = (self.workdir / "workspace" / "annotations.json").read_text()
        self.client.get("/changes?scope=hyderabad")
        self.client.get("/changes?scope=all&suppressed=1")
        after = (self.workdir / "workspace" / "annotations.json").read_text()
        self.assertEqual(before, after)

    def test_unacknowledging_legacy_state_shadows_it_for_this_scope_only(self) -> None:
        page = self.client.get(
            "/changes?scope=hyderabad&suppressed=1"
        ).data.decode("utf-8")
        subject = re.findall(r'<tr id="(change:v2:hyderabad:[^"]+)"', page)[0]
        response = self.client.post("/changes/annotate", data={
            "action": "unacknowledge", "subject": subject,
            "next": "/changes?scope=hyderabad&suppressed=1",
        }, follow_redirects=True)
        self.assertIn(b"Acknowledgement removed", response.data)

        annotations = self._annotations()
        # The legacy record is untouched...
        self.assertIn(self.legacy, annotations["change-ack"])
        self.assertEqual(
            "pre-isolation",
            annotations["change-ack"][self.legacy]["updated_by"],
        )
        # ...the scoped shadow exists and carries the explicit negative...
        self.assertIs(
            False, annotations["change-ack"][subject]["acknowledged"]
        )
        # ...this scope reads clean; the other still shows the legacy ack.
        hyd_row = re.search(
            r'<tr id="' + re.escape(subject) + r'".*?</tr>',
            self.client.get(
                "/changes?scope=hyderabad&suppressed=1"
            ).data.decode("utf-8"),
            re.DOTALL,
        ).group(0)
        self.assertNotIn("acknowledged", hyd_row)
        sec_page = self.client.get(
            "/changes?scope=secunderabad&suppressed=1"
        ).data.decode("utf-8")
        self.assertIn("acknowledged", sec_page)

    def test_unsuppressing_legacy_state_shadows_it_for_this_scope_only(self) -> None:
        page = self.client.get(
            "/changes?scope=hyderabad&suppressed=1"
        ).data.decode("utf-8")
        subject = re.findall(r'<tr id="(change:v2:hyderabad:[^"]+)"', page)[0]
        response = self.client.post("/changes/annotate", data={
            "action": "unsuppress", "subject": subject,
            "next": "/changes?scope=hyderabad",
        }, follow_redirects=True)
        self.assertIn(b"Suppression removed", response.data)

        annotations = self._annotations()
        self.assertIn(self.legacy, annotations["change-suppression"])
        self.assertIs(
            False,
            annotations["change-suppression"][subject]["suppressed"],
        )
        # Hyderabad shows the row again; Secunderabad still hides it.
        hyd_page = self.client.get(
            "/changes?scope=hyderabad"
        ).data.decode("utf-8")
        self.assertIn(subject, hyd_page)
        sec_page = self.client.get(
            "/changes?scope=secunderabad"
        ).data.decode("utf-8")
        self.assertIn("suppressed change(s) hidden", sec_page)

    def test_acting_positively_on_legacy_state_writes_v2_only(self) -> None:
        page = self.client.get(
            "/changes?scope=hyderabad&suppressed=1"
        ).data.decode("utf-8")
        subject = re.findall(r'<tr id="(change:v2:hyderabad:[^"]+)"', page)[0]
        self.client.post("/changes/annotate", data={
            "action": "assign", "subject": subject, "owner": "site-owner",
            "next": "/changes?scope=hyderabad&suppressed=1",
        }, follow_redirects=True)
        annotations = self._annotations()
        self.assertIn(subject, annotations.get("change-assignment", {}))
        self.assertNotIn(self.legacy, annotations.get("change-assignment", {}))


if __name__ == "__main__":
    unittest.main()
