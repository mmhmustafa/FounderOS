"""POST /changes/bulk — endpoint, confirm pages, UI gating, chronicle.

The product rule under test everywhere: bulk convenience never
collapses per-change truth. 7 updated / 2 unchanged / 1 not-present is
never rendered as 10 succeeded; forged, stale, foreign-scope and
oversized requests mutate nothing; and one batch is ONE Timeline row
backed by N audit events.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


def _report(changes) -> dict:
    return {"generated_at": "2026-08-13T02:00:00+00:00", "changes": changes}


def _change(tag: str, severity: str = "high") -> dict:
    return {
        "category": "neighbor", "severity": severity, "subject": f"R-{tag}",
        "field": "bgp-neighbor", "previous_value": "Established",
        "current_value": "Idle",
        "description": f"{tag} BGP neighbour went to Idle",
    }


def _nested_form_depth(html: str) -> int:
    """Maximum <form> nesting depth in rendered markup."""

    depth = deepest = 0
    for token in re.findall(r"<form\b|</form>", html):
        depth += 1 if token.startswith("<form") else -1
        deepest = max(deepest, depth)
    return deepest


class _WorldMixin:
    """A two-profile world with real change rows in each scope."""

    HYD_CHANGES = [_change("alpha"), _change("beta"), _change("gamma")]
    SEC_CHANGES = [_change("alpha")]  # the same delta, other scope

    def build(self, tmp: str, *, hyderabad=None):
        from founderos_atlas.workspace import profile_scope

        self.workdir = Path(tmp)
        _service, self.client = build_world(self.workdir)
        hyd = profile_scope(self.workdir, "hyderabad", "Hyderabad")
        sec = profile_scope(self.workdir, "secunderabad", "Secunderabad")
        (hyd.output_dir / "change_report.json").write_text(
            json.dumps(_report(hyderabad or self.HYD_CHANGES)),
            encoding="utf-8",
        )
        (sec.output_dir / "change_report.json").write_text(
            json.dumps(_report(self.SEC_CHANGES)), encoding="utf-8"
        )

    def subjects(self, scope: str, *, suppressed: bool = False) -> list[str]:
        query = f"/changes?scope={scope}" + ("&suppressed=1" if suppressed else "")
        page = self.client.get(query).data.decode("utf-8")
        return re.findall(r'<tr id="(change:v2:[^"]+)"', page)

    def bulk(self, data: dict, follow: bool = True):
        return self.client.post("/changes/bulk", data=data,
                                follow_redirects=follow)

    def annotations(self) -> dict:
        path = self.workdir / "workspace" / "annotations.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))["annotations"]

    def audit_lines(self) -> list[dict]:
        path = self.workdir / "workspace" / "audit.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()]


class BulkEndpointTests(_WorldMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.build(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_direct_acknowledge_reports_per_subject_truth(self) -> None:
        subjects = self.subjects("hyderabad")
        # Pre-acknowledge one of them the single-row way.
        self.client.post("/changes/annotate", data={
            "action": "acknowledge", "subject": subjects[0],
            "next": "/changes?scope=hyderabad",
        })
        forged = "change:v2:hyderabad:00000000000000000000"
        response = self.bulk({
            "bulk_action": "acknowledge",
            "subjects": [subjects[0], subjects[1], forged],
            "next": "/changes?scope=hyderabad",
        })
        body = response.data.decode("utf-8")
        self.assertIn("3 change(s)", body)
        self.assertIn("1 acknowledged", body)
        self.assertIn("1 already acknowledged", body)
        self.assertIn("1 no longer present in this view", body)
        # The forged subject wrote nothing.
        self.assertNotIn(forged, json.dumps(self.annotations()))
        # And the review affordance is offered.
        self.assertIn("Review this batch", body)

    def test_oversized_batches_are_rejected_never_truncated(self) -> None:
        subjects = [f"change:v2:hyderabad:{i:020d}" for i in range(201)]
        before = self.annotations()
        response = self.bulk({
            "bulk_action": "acknowledge", "subjects": subjects,
            "next": "/changes?scope=hyderabad",
        })
        self.assertIn(b"limited to 200", response.data)
        self.assertIn(b"Nothing was changed", response.data)
        self.assertEqual(before, self.annotations())

    def test_duplicates_count_once_and_empty_selection_is_refused(self) -> None:
        subjects = self.subjects("hyderabad")
        response = self.bulk({
            "bulk_action": "acknowledge",
            "subjects": [subjects[0]] * 3 + [subjects[1]],
            "next": "/changes?scope=hyderabad",
        })
        self.assertIn(b"2 change(s)", response.data)
        refused = self.bulk({
            "bulk_action": "acknowledge", "subjects": [],
            "next": "/changes?scope=hyderabad",
        })
        self.assertIn(b"Select at least one change.", refused.data)
        unknown = self.bulk({
            "bulk_action": "explode", "subjects": [subjects[0]],
            "next": "/changes?scope=hyderabad",
        })
        self.assertIn(b"Unknown bulk action.", unknown.data)

    def test_foreign_scope_subject_is_not_present_and_untouched(self) -> None:
        secunderabad = self.subjects("secunderabad")[0]
        hyderabad = self.subjects("hyderabad")[0]
        response = self.bulk({
            "bulk_action": "acknowledge",
            "subjects": [hyderabad, secunderabad],
            "next": "/changes?scope=hyderabad",
        })
        body = response.data.decode("utf-8")
        self.assertIn("1 acknowledged", body)
        self.assertIn("1 no longer present in this view", body)
        self.assertNotIn(secunderabad, json.dumps(self.annotations()))

    def test_double_submit_converges_to_no_change_with_no_new_audit(self) -> None:
        subjects = self.subjects("hyderabad")[:2]
        self.bulk({"bulk_action": "acknowledge", "subjects": subjects,
                   "next": "/changes?scope=hyderabad"})
        audit_after_first = len(self.audit_lines())
        second = self.bulk({"bulk_action": "acknowledge", "subjects": subjects,
                            "next": "/changes?scope=hyderabad"})
        self.assertIn(
            b"No change \xe2\x80\x94 all 2 selected change(s) were already "
            b"acknowledged.", second.data,
        )
        self.assertEqual(audit_after_first, len(self.audit_lines()),
                         "a no-op batch must write no audit events")

    def test_bulk_unsuppress_shadows_legacy_state_only(self) -> None:
        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.change.identity import legacy_subject_of

        subject = self.subjects("hyderabad")[0]
        legacy = legacy_subject_of(subject)
        AnnotationStore(self.workdir / "workspace").set(
            kind="change-suppression", subject=legacy,
            fields={"reason": "legacy suppression"}, actor="pre-isolation",
        )
        response = self.bulk({
            "bulk_action": "unsuppress",
            "subjects": [subject],
            "next": "/changes?scope=hyderabad&suppressed=1",
        })
        self.assertIn(b"1 unsuppressed", response.data)
        annotations = self.annotations()["change-suppression"]
        self.assertIn(legacy, annotations, "legacy record is read-only")
        self.assertIs(False, annotations[subject]["suppressed"])

    def test_tampered_next_falls_back(self) -> None:
        subject = self.subjects("hyderabad")[0]
        response = self.bulk({
            "bulk_action": "acknowledge", "subjects": [subject],
            "next": "https://evil.example/phish",
        }, follow=False)
        location = response.headers["Location"]
        self.assertTrue(location.startswith("/changes"),
                        f"open redirect: {location}")

    def test_batch_review_shows_exactly_the_batch_including_suppressed(self) -> None:
        subjects = self.subjects("hyderabad")
        # Confirmed bulk suppress of two rows.
        response = self.bulk({
            "bulk_action": "suppress", "confirmed": "1",
            "reason": "planned maintenance",
            "subjects": subjects[:2],
            "next": "/changes?scope=hyderabad",
        }, follow=False)
        location = response.headers["Location"]
        correlation = re.search(r"batch_done=(bulk%3A[0-9a-f]+|bulk:[0-9a-f]+)",
                                location).group(1).replace("%3A", ":")
        # The default view hides them...
        default = self.client.get("/changes?scope=hyderabad").data.decode()
        self.assertIn("2 suppressed change(s) hidden", default)
        # ...the batch view shows exactly them, suppressed included.
        review = self.client.get(
            f"/changes?scope=hyderabad&batch={correlation}"
        ).data.decode("utf-8")
        rows = re.findall(r'<tr id="(change:v2:[^"]+)"', review)
        self.assertEqual(sorted(subjects[:2]), sorted(rows))
        self.assertIn("Showing the changes of batch", review)
        self.assertIn("Audit detail", review)

    def test_write_amplification_guard_50_subjects(self) -> None:
        """One annotation write + one audit block for a 50-subject batch
        — the measured naive loop did 100 full-file rewrites."""

        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.audit.log import AuditLog

        self._tmp.cleanup()
        self._tmp = tempfile.TemporaryDirectory()
        self.build(self._tmp.name,
                   hyderabad=[_change(f"n{i:02d}") for i in range(50)])
        subjects = self.subjects("hyderabad")
        self.assertEqual(50, len(subjects))

        annotation_writes = []
        audit_blocks = []
        original_write = AnnotationStore._write
        original_append = AuditLog.append_many

        def counting_write(self, data):
            annotation_writes.append(1)
            return original_write(self, data)

        def counting_append(self, events):
            audit_blocks.append(len(tuple(events)))
            return original_append(self, events)

        AnnotationStore._write = counting_write
        AuditLog.append_many = counting_append
        try:
            response = self.bulk({
                "bulk_action": "acknowledge", "subjects": subjects,
                "next": "/changes?scope=hyderabad",
            })
        finally:
            AnnotationStore._write = original_write
            AuditLog.append_many = original_append
        self.assertIn(b"50 acknowledged", response.data)
        self.assertEqual(1, len(annotation_writes))
        self.assertEqual([50], audit_blocks)

    # -- single-row convergence ---------------------------------------------

    def test_single_row_forged_subject_writes_no_orphan(self) -> None:
        before = self.annotations()
        response = self.client.post("/changes/annotate", data={
            "action": "acknowledge",
            "subject": "change:v2:hyderabad:deadbeefdeadbeefdead",
            "next": "/changes?scope=hyderabad",
        }, follow_redirects=True)
        self.assertIn(b"not part of this view", response.data)
        self.assertEqual(before, self.annotations())

    def test_single_row_actions_on_real_rows_are_unchanged(self) -> None:
        subject = self.subjects("hyderabad")[0]
        response = self.client.post("/changes/annotate", data={
            "action": "note", "subject": subject, "note": "still works",
            "next": "/changes?scope=hyderabad",
        }, follow_redirects=True)
        self.assertIn(b"Note attached (audited).", response.data)
        self.assertIn(subject, self.annotations()["change-note"])


class BulkConfirmTests(_WorldMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.build(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_assign_first_post_renders_confirm_and_mutates_nothing(self) -> None:
        from founderos_atlas.audit import AnnotationStore

        subjects = self.subjects("hyderabad")
        AnnotationStore(self.workdir / "workspace").set(
            kind="change-assignment", subject=subjects[0],
            fields={"owner": "sara"},
        )
        before = self.annotations()
        response = self.bulk({
            "bulk_action": "assign", "subjects": subjects,
            "next": "/changes?scope=hyderabad",
        })
        body = response.data.decode("utf-8")
        self.assertEqual(200, response.status_code)
        self.assertIn("Assign 3 change(s)", body)
        self.assertIn("2 are unassigned", body)
        self.assertIn("1 already have an owner", body)
        self.assertIn("replaced", body)
        self.assertEqual(before, self.annotations(), "a preview never writes")
        # The selection rides along as hidden inputs, never a URL.
        for subject in subjects:
            self.assertIn(f'name="subjects" value="{subject}"', body)

    def test_confirmed_assign_replaces_and_reports_truthfully(self) -> None:
        from founderos_atlas.audit import AnnotationStore

        subjects = self.subjects("hyderabad")
        store = AnnotationStore(self.workdir / "workspace")
        store.set(kind="change-assignment", subject=subjects[0],
                  fields={"owner": "sara"})
        store.set(kind="change-assignment", subject=subjects[1],
                  fields={"owner": "ahmed"})
        response = self.bulk({
            "bulk_action": "assign", "confirmed": "1", "owner": "ahmed",
            "subjects": subjects,
            "next": "/changes?scope=hyderabad",
        })
        body = response.data.decode("utf-8")
        self.assertIn("3 change(s)", body)
        self.assertIn("2 assigned to ahmed", body)      # sara-replacement + unassigned
        self.assertIn("1 already assigned to this owner", body)
        self.assertEqual(
            "ahmed",
            self.annotations()["change-assignment"][subjects[0]]["owner"],
        )

    def test_confirmed_assign_without_owner_rerenders_with_selection(self) -> None:
        subjects = self.subjects("hyderabad")
        before = self.annotations()
        response = self.bulk({
            "bulk_action": "assign", "confirmed": "1", "owner": "  ",
            "subjects": subjects, "next": "/changes?scope=hyderabad",
        })
        body = response.data.decode("utf-8")
        self.assertEqual(200, response.status_code)
        self.assertIn("An owner is required.", body)
        self.assertIn(f'value="{subjects[0]}"', body)
        self.assertEqual(before, self.annotations())

    def test_suppress_confirm_page_and_required_reason(self) -> None:
        subjects = self.subjects("hyderabad")
        preview = self.bulk({
            "bulk_action": "suppress", "subjects": subjects[:2],
            "next": "/changes?scope=hyderabad",
        })
        body = preview.data.decode("utf-8")
        self.assertIn("Suppress 2 change(s)", body)
        self.assertIn("2 will be newly suppressed", body)
        self.assertIn("reversible", body)
        refused = self.bulk({
            "bulk_action": "suppress", "confirmed": "1", "reason": "",
            "subjects": subjects[:2], "next": "/changes?scope=hyderabad",
        })
        self.assertIn(b"A reason is required.", refused.data)
        self.assertEqual({}, self.annotations().get("change-suppression", {}))

    def test_suppress_same_vs_different_reason_truth(self) -> None:
        from founderos_atlas.audit import AnnotationStore

        subjects = self.subjects("hyderabad")
        AnnotationStore(self.workdir / "workspace").set(
            kind="change-suppression", subject=subjects[0],
            fields={"reason": "planned maintenance"},
        )
        response = self.bulk({
            "bulk_action": "suppress", "confirmed": "1",
            "reason": "planned maintenance",
            "subjects": subjects[:2], "next": "/changes?scope=hyderabad",
        })
        body = response.data.decode("utf-8")
        self.assertIn("1 suppressed", body)
        self.assertIn("1 already suppressed with this reason", body)
        # A DIFFERENT reason is an update, never silently dropped.
        second = self.bulk({
            "bulk_action": "suppress", "confirmed": "1",
            "reason": "emergency change window",
            "subjects": [subjects[0]], "next": "/changes?scope=hyderabad",
        })
        self.assertIn(b"1 suppressed", second.data)
        self.assertEqual(
            "emergency change window",
            self.annotations()["change-suppression"][subjects[0]]["reason"],
        )


class BulkMarkupTests(_WorldMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.build(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_nested_forms_and_sibling_bulk_form(self) -> None:
        page = self.client.get("/changes?scope=hyderabad").data.decode("utf-8")
        self.assertEqual(1, _nested_form_depth(page),
                         "a nested form would swallow the per-row POSTs")
        self.assertIn('id="changes-bulk"', page)
        # The bulk form is AFTER the table, never wrapping it.
        self.assertLess(page.index("</table>"), page.index('id="changes-bulk"'))
        self.assertIn('form="changes-bulk"', page)
        self.assertIn('action="/changes/bulk"', page)

    def test_select_all_and_count_say_on_this_page(self) -> None:
        page = self.client.get("/changes?scope=hyderabad").data.decode("utf-8")
        self.assertIn("Select all 3 changes on this page", page)
        self.assertIn("{checked} of {total} on this page selected", page)

    def test_row_checkboxes_carry_identifying_names(self) -> None:
        page = self.client.get("/changes?scope=hyderabad").data.decode("utf-8")
        self.assertIn("Select the high topology change on R-alpha", page)

    def test_no_bulk_note_action_but_row_note_survives(self) -> None:
        page = self.client.get("/changes?scope=hyderabad").data.decode("utf-8")
        bulk_form = page.split('id="changes-bulk"')[1].split("</form>")[0]
        self.assertNotIn('value="note"', bulk_form)
        self.assertIn('name="action" value="note"', page,
                      "the single-row Note form must survive untouched")

    def test_clear_selection_and_engine_wiring_present(self) -> None:
        page = self.client.get("/changes?scope=hyderabad").data.decode("utf-8")
        self.assertIn("data-clear-selection", page)
        self.assertIn('data-row-select="subjects"', page)
        js = Path("src/founderos_atlas/web/static/atlas.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("data-clear-selection", js)
        self.assertIn("data-selection-phrase", js)


class BulkRoleTests(unittest.TestCase):
    """Selection, Act menu and bulk bar exist exactly for principals
    holding changes.annotate — everyone else keeps readable data with
    zero dead controls (the D3 fix)."""

    PASSWORDS = {
        "vera": "viewer-password-abc123",
        "oper": "operator-password-abc1",
        "ivy": "invest-password-abc123",
    }
    ROLES = {"vera": "viewer", "oper": "network-operator",
             "ivy": "investigator"}

    @classmethod
    def setUpClass(cls) -> None:
        from founderos_atlas.access import UserStore
        from founderos_atlas.web import create_app
        from founderos_atlas.workspace import profile_scope
        from tests.test_federation import hyderabad_network
        from tests.test_profile_isolation import (
            FIXED, add_profile, make_service, run_discover,
        )

        cls._tmp = tempfile.TemporaryDirectory()
        workdir = Path(cls._tmp.name)
        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
        scope = profile_scope(workdir, "hyderabad", "Hyderabad")
        (scope.output_dir / "change_report.json").write_text(
            json.dumps(_report([_change("alpha"), _change("beta")])),
            encoding="utf-8",
        )
        workspace = workdir / "workspace"
        users = UserStore(workspace)
        for name, role in cls.ROLES.items():
            users.create(username=name, roles=(role,),
                         password=cls.PASSWORDS[name])
        cls.app = create_app(
            profile_service=service, output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workspace, auth_mode="password",
        )
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _page(self, username: str):
        client = self.app.test_client()
        response = client.post("/login", data={
            "username": username, "password": self.PASSWORDS[username],
        })
        self.assertEqual(302, response.status_code)
        page = client.get("/changes?scope=hyderabad")
        self.assertEqual(200, page.status_code)
        return client, page.data.decode("utf-8")

    def test_viewer_and_operator_get_data_without_dead_controls(self) -> None:
        for username in ("vera", "oper"):
            _client, page = self._page(username)
            self.assertIn("BGP neighbour went to Idle", page, username)
            self.assertNotIn('data-row-select="subjects"', page, username)
            self.assertNotIn('name="subjects"', page, username)
            self.assertNotIn('aria-label="Actions for this change', page,
                             username)
            self.assertNotIn('id="changes-bulk"', page, username)

    def test_investigator_gets_the_full_workflow(self) -> None:
        client, page = self._page("ivy")
        self.assertIn('data-row-select="subjects"', page)
        self.assertIn("data-select-all", page)
        self.assertIn(">Act", page)
        self.assertIn('id="changes-bulk"', page)
        # And the endpoint accepts her batch (CSRF included).
        subject = re.search(r'<tr id="(change:v2:[^"]+)"', page).group(1)
        csrf = client.get_cookie("atlas_csrf")
        response = client.post("/changes/bulk", data={
            "_csrf": csrf.value if csrf else "",
            "bulk_action": "acknowledge", "subjects": [subject],
            "next": "/changes?scope=hyderabad",
        }, follow_redirects=True)
        self.assertIn(b"1 acknowledged", response.data)


class BulkChronicleTests(_WorldMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.build(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_one_timeline_row_per_batch_full_truth_in_audit(self) -> None:
        subjects = self.subjects("hyderabad")
        self.bulk({"bulk_action": "acknowledge", "subjects": subjects,
                   "next": "/changes?scope=hyderabad"})
        correlation = next(
            line["correlation_id"] for line in self.audit_lines()
            if str(line.get("correlation_id") or "").startswith("bulk:")
        )
        timeline = self.client.get("/timeline?scope=hyderabad").data.decode(
            "utf-8"
        )
        self.assertIn("acknowledged 3 change(s)", timeline)
        # The title renders twice inside ONE row (cell text + the Open
        # record aria-label); the provenance string is once per row.
        self.assertEqual(
            1, timeline.count("audit batch bulk:"),
            "one operator row per batch",
        )
        self.assertNotIn("change-ack set:", timeline,
                         "no per-subject chronology rows for a batch")
        self.assertIn(f"/audit?correlation={correlation.replace(':', '%3A')}",
                      timeline)
        audit = self.client.get(
            f"/audit?correlation={correlation}"
        ).data.decode("utf-8")
        for subject in subjects:
            self.assertIn(subject, audit)

    def test_single_row_actions_keep_one_chronicle_row_each(self) -> None:
        subject = self.subjects("hyderabad")[0]
        self.client.post("/changes/annotate", data={
            "action": "acknowledge", "subject": subject,
            "next": "/changes?scope=hyderabad",
        })
        timeline = self.client.get("/timeline?scope=hyderabad").data.decode(
            "utf-8"
        )
        self.assertIn("change-ack set:", timeline,
                      "uncorrelated events are untouched")


if __name__ == "__main__":
    unittest.main()
