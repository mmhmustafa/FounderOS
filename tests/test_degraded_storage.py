"""Degraded storage must not cost Atlas its voice (PR-179 Step 3).

Measured before this change: a corrupt ``annotations.json`` — a
SECONDARY overlay file — took down /policy, /changes and /timeline with
a 500 (matrix row 7); one bad line in ``audit.jsonl`` lost the WHOLE
chronology on /timeline and /audit (row 8); a corrupt evidence or
configuration store rendered a complete-looking page with records
silently missing (row 18); and 400/403 raised outside the
before_request gate fell through to werkzeug's unbranded page.

The contract now: every one of those pages returns 200 with its
primary data, states LOUDLY and SPECIFICALLY what could not be read,
withholds every control that would WRITE to an unreadable store — a
write could overwrite the very bytes Atlas could not parse — and never
repairs, resets or deletes anything. A corrupt annotation store is
never silently treated as healthy or empty.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.audit import AnnotationStore, AuditLog
from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError

from tests.test_web_app import build_client, make_service


def flat(body: bytes | str) -> str:
    """Body text with template line-wraps collapsed, so a phrase split
    across a wrapped template line still matches."""

    text = body.decode("utf-8") if isinstance(body, bytes) else body
    return " ".join(text.split())


def corrupt_annotations(workdir: Path) -> Path:
    path = workdir / "workspace" / "annotations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"annotations": {truncated', encoding="utf-8")
    return path


class AnnotationStoreDegradedReadTests(unittest.TestCase):
    def test_read_all_reports_degraded_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "annotations.json").write_text("{oops", encoding="utf-8")
            store = AnnotationStore(root)
            data, degraded = store.read_all("change-ack", "change-note")
            self.assertTrue(degraded)
            self.assertEqual({"change-ack": {}, "change-note": {}}, data)
            # The strict readers keep their contract for non-render use.
            with self.assertRaises(WorkspaceCorruptedError):
                store.all("change-ack")

    def test_a_missing_file_is_empty_not_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data, degraded = AnnotationStore(Path(tmp)).read_all("change-ack")
            self.assertFalse(degraded)
            self.assertEqual({"change-ack": {}}, data)

    def test_writes_refuse_before_touching_a_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "annotations.json"
            path.write_text("{oops", encoding="utf-8")
            store = AnnotationStore(root)
            with self.assertRaises(WorkspaceCorruptedError):
                store.set(kind="change-ack", subject="s",
                          fields={"acknowledged": True})
            with self.assertRaises(WorkspaceCorruptedError):
                store.set_many(kind="change-ack",
                               records={"s": {"acknowledged": True}})
            # The file's bytes are exactly as the operator left them.
            self.assertEqual("{oops", path.read_text(encoding="utf-8"))


class AuditLogTolerantReadTests(unittest.TestCase):
    def _log_with_bad_line(self, root: Path) -> AuditLog:
        log = AuditLog(root)
        store = AnnotationStore(root)
        store.set(kind="change-ack", subject="change:v2:lab:abc",
                  fields={"acknowledged": True})
        with log.path.open("a", encoding="utf-8") as handle:
            handle.write("{this line is not json\n")
        return log

    def test_a_bad_line_is_skipped_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = self._log_with_bad_line(Path(tmp))
            events, skipped = log.events_tolerant()
            self.assertEqual(1, skipped)
            self.assertEqual(1, len(events))
            self.assertEqual("change:v2:lab:abc", events[0].subject)
            # The strict reader still refuses the whole file: callers
            # that must not tolerate a partial record keep that right.
            with self.assertRaises(WorkspaceCorruptedError):
                log.events()
            # Nothing was repaired: the bad line is still on disk.
            self.assertIn("{this line is not json",
                          log.path.read_text(encoding="utf-8"))

    def test_a_missing_log_is_empty_with_zero_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events, skipped = AuditLog(Path(tmp)).events_tolerant()
            self.assertEqual(((), 0), (events, skipped))


class CorruptAnnotationsPagesTests(unittest.TestCase):
    """B3: corrupt annotations can no longer 500 Policy/Changes/Timeline."""

    def test_pages_render_with_a_loud_specific_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            corrupt_annotations(workdir)
            for path in ("/changes", "/policy", "/timeline"):
                response = client.get(path)
                self.assertEqual(200, response.status_code, path)
                body = response.data.decode("utf-8")
                self.assertIn("could not be read", body, path)
                self.assertIn("/system/integrity", body, path)
                # No page leaks where the workspace lives.
                self.assertNotIn(tmp, body, path)
                self.assertNotIn("annotations.json", body, path)

    def test_changes_page_withholds_every_annotation_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            healthy = client.get("/changes").data.decode("utf-8")
            corrupt_annotations(workdir)
            degraded = client.get("/changes").data.decode("utf-8")
            for marker in ("data-bulk-bar", "data-row-select",
                           "/changes/bulk", "/changes/annotate"):
                self.assertNotIn(marker, degraded, marker)
            self.assertIn('data-degraded="annotations"', degraded)
            self.assertNotIn('data-degraded="annotations"', healthy)

    def test_policy_page_withholds_assignment_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            corrupt_annotations(workdir)
            body = client.get("/policy").data.decode("utf-8")
            self.assertNotIn("data-bulk-bar", body)
            self.assertNotIn("data-row-select", body)
            self.assertIn('data-degraded="annotations"', body)


class CorruptAnnotationsWriteRefusalTests(unittest.TestCase):
    """Writes are BLOCKED while the store is unreadable — refused
    loudly, with the stored bytes untouched (never auto-repaired)."""

    def test_bulk_action_refuses_and_leaves_the_file_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            path = corrupt_annotations(workdir)
            before = path.read_bytes()
            response = client.post("/changes/bulk", data={
                "bulk_action": "acknowledge",
                "subjects": ["change:v2:lab:deadbeefdeadbeef"],
                "next": "/changes",
            }, follow_redirects=True)
            self.assertEqual(200, response.status_code)
            body = response.data.decode("utf-8")
            self.assertIn("cannot apply bulk actions", body)
            self.assertIn("Nothing was changed", body)
            self.assertEqual(before, path.read_bytes())

    def test_policy_assign_refuses_and_leaves_the_file_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            path = corrupt_annotations(workdir)
            before = path.read_bytes()
            response = client.post("/policy/assign", data={
                "owner": "netops",
                "subjects": ["policy-result:x:y"],
                "next": "/policy",
            }, follow_redirects=True)
            self.assertEqual(200, response.status_code)
            self.assertIn("cannot save assignments",
                          response.data.decode("utf-8"))
            self.assertEqual(before, path.read_bytes())

    def test_configuration_annotation_refuses_without_a_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            path = corrupt_annotations(workdir)
            before = path.read_bytes()
            response = client.post("/configuration/dev-1/annotation", data={
                "note": "a note", "reason": "because",
            })
            self.assertEqual(302, response.status_code)
            self.assertEqual(before, path.read_bytes())


class CorruptAuditLinePagesTests(unittest.TestCase):
    """Row 8: one bad line loses ONE line, visibly — not the record."""

    def _client_with_bad_audit_line(self, workdir: Path):
        _, client = build_client(workdir, make_service(workdir))
        workspace = workdir / "workspace"
        AnnotationStore(workspace).set(
            kind="change-ack", subject="change:v2:lab:abc",
            fields={"acknowledged": True},
        )
        with (workspace / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write("{corrupted tail\n")
        return client

    def test_audit_page_shows_readable_events_and_states_the_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_bad_audit_line(Path(tmp))
            response = client.get("/audit")
            self.assertEqual(200, response.status_code)
            body = flat(response.data)
            self.assertIn("change:v2:lab:abc", body)
            self.assertIn("1 audit entry could not be read", body)
            self.assertIn('data-degraded="audit"', body)

    def test_timeline_states_the_gap_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_bad_audit_line(Path(tmp))
            response = client.get("/timeline")
            self.assertEqual(200, response.status_code)
            self.assertIn("1 audit entry could not be read",
                          flat(response.data))

    def test_export_still_serves_every_readable_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_bad_audit_line(Path(tmp))
            response = client.get("/audit/export.csv")
            self.assertEqual(200, response.status_code)
            self.assertIn("change:v2:lab:abc",
                          response.data.decode("utf-8"))

    def test_healthy_log_shows_no_gap_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            body = client.get("/audit").data.decode("utf-8")
            self.assertNotIn('data-degraded="audit"', body)


class StoreOmissionCountTests(unittest.TestCase):
    """Row 18: a corrupt stored record is a COUNTED, STATED omission."""

    def test_enterprise_memory_counts_unparseable_files(self) -> None:
        from founderos_atlas.enterprise_memory.store import (
            EnterpriseMemoryStore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = EnterpriseMemoryStore(root)
            target = root / "record.json"
            target.write_text('{"ok": true}', encoding="utf-8")
            self.assertEqual({"ok": True}, store._read(target, {}))
            self.assertEqual(0, store.unreadable_count)
            target.write_text('{"truncated', encoding="utf-8")
            self.assertEqual({}, store._read(target, {}))
            self.assertEqual(1, store.unreadable_count)
            # Recovery is observed, never performed: when the file
            # parses again the omission clears on the next read.
            target.write_text('{"ok": true}', encoding="utf-8")
            store._read(target, {})
            self.assertEqual(0, store.unreadable_count)

    def test_config_memory_distinguishes_unreadable_from_empty(self) -> None:
        from founderos_atlas.config_memory import ConfigMemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigMemoryStore(Path(tmp) / "config-memory")
            self.assertFalse(store.index_unreadable())  # missing = empty
            store.index_path.parent.mkdir(parents=True, exist_ok=True)
            store.index_path.write_text("{nope", encoding="utf-8")
            self.assertTrue(store.index_unreadable())
            # The tolerant loader still answers without raising, so the
            # page keeps rendering — the FLAG is what stops "unreadable"
            # being presented as "nothing is remembered".
            self.assertEqual((), store.histories())

    def test_configuration_page_states_an_unreadable_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            index = workdir / "out" / "config-memory" / "index.json"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text("{nope", encoding="utf-8")
            # The Enterprise aggregation excludes a data-less local
            # workspace, so ask for that scope directly — the same
            # store the operator would open.
            response = client.get("/configuration?scope=default")
            self.assertEqual(200, response.status_code)
            body = flat(response.data)
            self.assertIn('data-degraded="configuration"', body)
            self.assertIn("could not be read", body)
            self.assertNotIn(tmp, body)


class BrandedErrorPageTests(unittest.TestCase):
    """Row 12/18 tail: no unbranded werkzeug page survives, and an
    unknown record answers 404 everywhere — not a flash on one page
    and a 404 on another."""

    def test_unknown_configuration_record_answers_honestly(self) -> None:
        # Row 12 (strict 404 here) was tried and reverted as not-free:
        # device menus legitimately render a Configuration link for a
        # device whose configuration is not remembered yet, and a
        # rendered link must never 404 (test_navigation's contract).
        # The honest flash-redirect stays; the decision is recorded in
        # the PR-179 handover.
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            response = client.get(
                "/configuration/no-such-device", follow_redirects=True
            )
            self.assertEqual(200, response.status_code)
            body = response.data.decode("utf-8")
            self.assertIn("no remembered configuration", body)

    def test_400_renders_the_branded_page_not_werkzeugs(self) -> None:
        # A real route that aborts 400 on an HTML form POST: the PRISM
        # playground export with an unsupported format. Before the
        # PR-179 handler this fell through to werkzeug's unbranded
        # default page.
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            response = client.post(
                "/prism/playground/export", data={"format": "exe"},
            )
            self.assertEqual(400, response.status_code)
            body = response.data.decode("utf-8")
            self.assertIn("Unsupported export format.", body)
            self.assertNotIn("The browser (or proxy)", body)
            self.assertIn("Atlas", body)

    def test_api_400_stays_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            response = client.put(
                "/api/topology/site-assignments",
                data="[]", content_type="application/json",
            )
            self.assertEqual(400, response.status_code)
            payload = json.loads(response.data)
            self.assertIn("JSON object is required", payload["error"])

    def test_api_403_names_the_cross_origin_refusal(self) -> None:
        # The only in-repo abort(403) is the cross-origin topology-edit
        # guard; the new handler answers it with the refusal named and
        # the correlation id attached, instead of werkzeug's default.
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            response = client.put(
                "/api/topology/site-assignments",
                data=json.dumps({"device_id": "d1", "site_id": "s1"}),
                content_type="application/json",
                headers={"Origin": "https://evil.example"},
            )
            self.assertEqual(403, response.status_code)
            payload = json.loads(response.data)
            self.assertIn("Cross-origin", payload["error"])
            self.assertTrue(payload.get("correlation_id"))


if __name__ == "__main__":
    unittest.main()
