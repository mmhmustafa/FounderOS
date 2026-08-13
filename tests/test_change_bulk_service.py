"""Bulk change triage — batch primitives and the pure service (PR-178.2).

One operator intent over N subjects, without collapsing per-subject
truth: per-action UNCHANGED comparisons, no audit for no-ops, one
correlation id, at most two annotation writes per batch, and a
compensating restore when the audit block fails.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _subject(scope: str, tag: str) -> str:
    return f"change:v2:{scope}:{tag.ljust(20, '0')[:20]}"


class BatchPrimitiveTests(unittest.TestCase):
    """AnnotationStore.set_many/clear_many + AuditLog.append_many."""

    def _store(self, tmp: str):
        from founderos_atlas.audit import AnnotationStore

        return AnnotationStore(Path(tmp))

    def _writes(self, store):
        """Count physical annotation-file writes."""

        calls = []
        original = store._write

        def counted(data):
            calls.append(1)
            return original(data)

        store._write = counted
        return calls

    def test_set_many_is_one_annotation_write_and_one_audit_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            writes = self._writes(store)
            subjects = {_subject("hyderabad", f"s{i:03d}"): {"acknowledged": True}
                        for i in range(50)}
            written = store.set_many(
                kind="change-ack", records=subjects, actor="ahmed",
                correlation_id="bulk:test-1",
                scope_ids={s: "hyderabad" for s in subjects},
            )
            self.assertEqual(50, len(written))
            self.assertEqual(1, len(writes), "one write for 50 subjects")
            lines = (Path(tmp) / "audit.jsonl").read_text().splitlines()
            self.assertEqual(50, len(lines))
            events = [json.loads(line) for line in lines]
            self.assertEqual({"bulk:test-1"},
                             {e["correlation_id"] for e in events})
            self.assertEqual({"hyderabad"}, {e["scope_id"] for e in events})
            self.assertEqual({"ahmed"}, {e["actor"] for e in events})

    def test_clear_many_shares_the_correlation_id_and_skips_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            present = _subject("hyderabad", "present")
            absent = _subject("hyderabad", "absent")
            store.set(kind="change-ack", subject=present,
                      fields={"acknowledged": True})
            cleared = store.clear_many(
                kind="change-ack", subjects=[present, absent],
                actor="ahmed", correlation_id="bulk:test-2",
                scope_ids={present: "hyderabad"},
            )
            self.assertEqual((present,), cleared)
            events = [json.loads(line) for line in
                      (Path(tmp) / "audit.jsonl").read_text().splitlines()]
            clears = [e for e in events if e["operation"] == "clear"]
            self.assertEqual(1, len(clears), "absent subject not audited")
            self.assertEqual("bulk:test-2", clears[0]["correlation_id"])

    def test_append_many_is_append_only(self) -> None:
        from founderos_atlas.audit import AuditEvent
        from founderos_atlas.audit.log import AuditLog

        with tempfile.TemporaryDirectory() as tmp:
            log = AuditLog(Path(tmp))
            log.append(AuditEvent.create(
                category="seed", operation="set", subject="seed:1"))
            historical = (Path(tmp) / "audit.jsonl").read_text()
            log.append_many([
                AuditEvent.create(category="change-ack", operation="set",
                                  subject=_subject("h", f"b{i}"))
                for i in range(5)
            ])
            after = (Path(tmp) / "audit.jsonl").read_text()
            self.assertTrue(after.startswith(historical))
            self.assertEqual(6, len(after.splitlines()))

    def test_audit_failure_restores_the_annotation_pre_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            keep = _subject("hyderabad", "keep")
            store.set(kind="change-ack", subject=keep,
                      fields={"acknowledged": True})
            pre_image = (Path(tmp) / "annotations.json").read_text()

            def broken(events):
                raise OSError("disk full")

            store._audit.append_many = broken
            with self.assertRaises(OSError):
                store.set_many(
                    kind="change-ack",
                    records={_subject("hyderabad", "new"):
                             {"acknowledged": True}},
                    actor="ahmed", correlation_id="bulk:fails",
                )
            self.assertEqual(
                pre_image, (Path(tmp) / "annotations.json").read_text(),
                "a mutation whose audit failed must not survive",
            )


class ClassifyTests(unittest.TestCase):
    """Per-action UNCHANGED semantics — the adversarial amendment."""

    HYD_A = _subject("hyderabad", "aaaa")
    HYD_B = _subject("hyderabad", "bbbb")
    HYD_C = _subject("hyderabad", "cccc")
    SEC_X = _subject("secunderabad", "xxxx")

    def _classify(self, action, subjects, annotations, **inputs):
        from founderos_atlas.change.bulk import classify

        valid = {self.HYD_A: "change:" + self.HYD_A.rsplit(":", 1)[1],
                 self.HYD_B: None, self.HYD_C: None}
        return classify(action=action, subjects=subjects,
                        valid_subjects=valid, annotations=annotations,
                        **inputs)

    def _outcomes(self, plan):
        return {e.subject: e.outcome for e in plan.entries}

    def test_acknowledge_mixed_state(self) -> None:
        plan = self._classify(
            "acknowledge", [self.HYD_A, self.HYD_B, self.SEC_X],
            {self.HYD_A: {"acknowledged": True}},
        )
        outcomes = self._outcomes(plan)
        self.assertEqual("unchanged", outcomes[self.HYD_A])
        self.assertEqual("updated", outcomes[self.HYD_B])
        self.assertEqual("not-present", outcomes[self.SEC_X],
                         "a foreign-scope subject is never mutated")

    def test_unacknowledge_mixed_state_with_legacy_shadow_split(self) -> None:
        legacy = "change:" + self.HYD_A.rsplit(":", 1)[1]
        plan = self._classify(
            "unacknowledge", [self.HYD_A, self.HYD_B, self.HYD_C],
            {legacy: {"acknowledged": True},          # legacy-asserted
             self.HYD_B: {"acknowledged": True}},     # scoped record
        )
        modes = {e.subject: e.mode for e in plan.entries}
        self.assertEqual("shadow", modes[self.HYD_A],
                         "legacy state is shadowed, never written through")
        self.assertEqual("clear", modes[self.HYD_B])
        self.assertEqual(
            "unchanged", self._outcomes(plan)[self.HYD_C],
        )

    def test_assign_same_owner_unchanged_different_owner_updated(self) -> None:
        plan = self._classify(
            "assign", [self.HYD_A, self.HYD_B, self.HYD_C],
            {self.HYD_A: {"owner": "ahmed"},
             self.HYD_B: {"owner": "sara"}},
            owner="ahmed",
        )
        outcomes = self._outcomes(plan)
        details = {e.subject: e.detail for e in plan.entries}
        self.assertEqual("unchanged", outcomes[self.HYD_A])
        self.assertEqual("same-owner", details[self.HYD_A])
        self.assertEqual("updated", outcomes[self.HYD_B],
                         "a DIFFERENT owner is a real replacement")
        self.assertEqual("other-owner", details[self.HYD_B])
        self.assertEqual("unassigned", details[self.HYD_C])

    def test_suppress_same_reason_unchanged_different_reason_updated(self) -> None:
        plan = self._classify(
            "suppress", [self.HYD_A, self.HYD_B, self.HYD_C],
            {self.HYD_A: {"reason": "planned work"},
             self.HYD_B: {"reason": "some other cause"}},
            reason="planned work",
        )
        outcomes = self._outcomes(plan)
        details = {e.subject: e.detail for e in plan.entries}
        self.assertEqual("unchanged", outcomes[self.HYD_A])
        self.assertEqual("updated", outcomes[self.HYD_B],
                         "a DIFFERENT reason must not be silently dropped")
        self.assertEqual("different-reason", details[self.HYD_B])
        self.assertEqual("new", details[self.HYD_C])

    def test_unsuppress_mixed_state(self) -> None:
        legacy = "change:" + self.HYD_A.rsplit(":", 1)[1]
        plan = self._classify(
            "unsuppress", [self.HYD_A, self.HYD_B, self.HYD_C],
            {legacy: {"reason": "legacy"},
             self.HYD_B: {"reason": "scoped"}},
        )
        modes = {e.subject: e.mode for e in plan.entries}
        self.assertEqual("shadow", modes[self.HYD_A])
        self.assertEqual("clear", modes[self.HYD_B])
        self.assertEqual("unchanged", self._outcomes(plan)[self.HYD_C])

    def test_a_scoped_negative_means_not_in_state(self) -> None:
        plan = self._classify(
            "unacknowledge", [self.HYD_A],
            {self.HYD_A: {"acknowledged": False},
             "change:" + self.HYD_A.rsplit(":", 1)[1]:
                 {"acknowledged": True}},
        )
        self.assertEqual("unchanged", self._outcomes(plan)[self.HYD_A],
                         "the scoped negative wins over the legacy positive")

    def test_dedupe_and_unknown_action(self) -> None:
        from founderos_atlas.change.bulk import classify, dedupe_subjects

        self.assertEqual([self.HYD_A, self.HYD_B], dedupe_subjects(
            [self.HYD_A, self.HYD_B, self.HYD_A, " ", self.HYD_B]))
        with self.assertRaises(ValueError):
            classify(action="explode", subjects=[], valid_subjects={},
                     annotations={})


class ExecuteTests(unittest.TestCase):
    HYD_A = _subject("hyderabad", "aaaa")
    HYD_B = _subject("hyderabad", "bbbb")
    SEC_X = _subject("secunderabad", "xxxx")

    def test_execute_writes_once_audits_updated_only_one_correlation(self) -> None:
        from founderos_atlas.audit import AnnotationStore
        from founderos_atlas.change.bulk import classify, execute

        with tempfile.TemporaryDirectory() as tmp:
            store = AnnotationStore(Path(tmp))
            store.set(kind="change-ack", subject=self.HYD_A,
                      fields={"acknowledged": True})
            historical = (Path(tmp) / "audit.jsonl").read_text()
            plan = classify(
                action="acknowledge",
                subjects=[self.HYD_A, self.HYD_B, self.SEC_X],
                valid_subjects={self.HYD_A: None, self.HYD_B: None},
                annotations=store.all("change-ack"),
            )
            result = execute(store, plan, actor="ahmed",
                             actor_roles=("investigator",))
            self.assertEqual(
                {"updated": 1, "unchanged": 1, "not-present": 1},
                result.counts,
            )
            self.assertTrue(result.correlation_id.startswith("bulk:"))
            new_events = [
                json.loads(line) for line in
                (Path(tmp) / "audit.jsonl").read_text()
                [len(historical):].splitlines()
            ]
            self.assertEqual(1, len(new_events),
                             "UNCHANGED and NOT_PRESENT get no audit event")
            self.assertEqual(self.HYD_B, new_events[0]["subject"])
            self.assertEqual("hyderabad", new_events[0]["scope_id"])
            self.assertEqual(result.correlation_id,
                             new_events[0]["correlation_id"])
            self.assertEqual(["investigator"], new_events[0]["actor_roles"])
            # And the unchanged subject's record was not rewritten.
            self.assertNotIn(
                "updated_by\": \"ahmed", json.dumps(
                    store.get("change-ack", self.HYD_A)),
            )

    def test_summary_sentence_truth(self) -> None:
        from founderos_atlas.change.bulk import BatchResult, summary_sentence

        sentence = summary_sentence(BatchResult(
            action="suppress", correlation_id="bulk:x",
            counts={"updated": 9, "unchanged": 2, "not-present": 1},
            reason="planned",
        ))
        self.assertEqual(
            "12 change(s) · 9 suppressed · 2 already suppressed with this "
            "reason · 1 no longer present in this view.",
            sentence,
        )
        zero = summary_sentence(BatchResult(
            action="acknowledge", correlation_id="bulk:y",
            counts={"updated": 0, "unchanged": 12, "not-present": 0},
        ))
        self.assertEqual(
            "No change — all 12 selected change(s) were already "
            "acknowledged.", zero,
        )
        assign = summary_sentence(BatchResult(
            action="assign", correlation_id="bulk:z",
            counts={"updated": 3, "unchanged": 0, "not-present": 0},
            owner="ahmed",
        ))
        self.assertIn("3 assigned to ahmed", assign)


if __name__ == "__main__":
    unittest.main()
