"""/policy report LRU cache (PR-176).

The previous cache held ONE report, so every scope switch — including
switching straight back — was a full cold render (~10 s measured on the
reference estate). These tests pin the bounded LRU that replaced it:
scope A → B → A serves A's report from cache and never serves one
scope's report for another; an evidence write and a governance revision
change still invalidate deterministically; and the Atlas version is a
key dimension, so an upgrade can never serve a report computed by older
evaluation semantics.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from founderos_atlas.policy import PolicyEngine

from tests.test_polish import build_world


def _counting_engine():
    calls = []
    original = PolicyEngine.evaluate_scopes

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    return calls, patch.object(PolicyEngine, "evaluate_scopes", counted)


def _touch_evidence(workdir: Path) -> int:
    """Bump every store's records.json stamp, as a discovery write would."""

    touched = 0
    for records in workdir.glob("**/enterprise-memory/evidence/records.json"):
        stamp = records.stat()
        os.utime(records, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
        touched += 1
    return touched


class PolicyReportLruTests(unittest.TestCase):
    """T5–T7 of the PR-176 test plan, at the route level."""

    def test_scope_a_b_a_serves_the_return_from_cache(self) -> None:
        # T7: the measured defect was that switching BACK to a scope paid
        # a full cold render. With the LRU, only first visits evaluate.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            calls, patcher = _counting_engine()
            with patcher:
                self.assertEqual(200, client.get("/policy?scope=hyderabad").status_code)
                after_a = len(calls)
                self.assertEqual(200, client.get("/policy?scope=secunderabad").status_code)
                after_b = len(calls)
                self.assertGreater(after_b, after_a, "scope B is a different report")
                self.assertEqual(200, client.get("/policy?scope=hyderabad").status_code)
                self.assertEqual(
                    after_b, len(calls),
                    "returning to scope A must be served from cache",
                )
                self.assertEqual(200, client.get("/policy?scope=all").status_code)
                after_all = len(calls)
                self.assertGreater(after_all, after_b)
                self.assertEqual(200, client.get("/policy?scope=secunderabad").status_code)
                self.assertEqual(
                    after_all, len(calls),
                    "three scopes must coexist in the cache",
                )

    def test_no_scopes_report_is_served_for_another(self) -> None:
        # T7's correctness half: after the A→B→A dance, each page still
        # shows ITS scope's devices — never a neighbour's cached report.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            a = client.get("/policy?scope=hyderabad").data
            b = client.get("/policy?scope=secunderabad").data
            a_again = client.get("/policy?scope=hyderabad").data
            for page in (a, a_again):
                self.assertIn(b"A1", page)          # Hyderabad's device
                self.assertNotIn(b"B1", page)       # Secunderabad's device
            self.assertIn(b"B1", b)
            self.assertNotIn(b"A1", b)
            both = client.get("/policy?scope=all").data
            self.assertIn(b"A1", both)
            self.assertIn(b"B1", both)

    def test_evidence_write_invalidates_deterministically(self) -> None:
        # T5: any store write updates records.json's stamp; the stamp is
        # in the key, so the very next request re-evaluates.
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            calls, patcher = _counting_engine()
            with patcher:
                client.get("/policy?scope=all")
                first = len(calls)
                client.get("/policy?scope=all")
                self.assertEqual(first, len(calls), "unchanged store: cache hit")
                self.assertGreater(_touch_evidence(workdir), 0, "no evidence store found")
                client.get("/policy?scope=all")
                self.assertGreater(
                    len(calls), first,
                    "a changed evidence store must re-evaluate",
                )

    def test_governance_revision_change_rebuilds_the_report(self) -> None:
        # T6: the governance revision is a key dimension, so activating
        # or editing a baseline is reflected on the next render.
        from founderos_atlas.policy.governance import PolicyGovernanceRepository

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            calls, patcher = _counting_engine()
            with patcher:
                client.get("/policy?scope=all")
                first = len(calls)
                with patch.object(
                    PolicyGovernanceRepository, "revision",
                    return_value=987654321,
                ):
                    client.get("/policy?scope=all")
                self.assertGreater(
                    len(calls), first,
                    "a governance revision change must re-evaluate",
                )

    def test_an_atlas_upgrade_never_serves_an_old_report(self) -> None:
        # PR-176: evaluation semantics can change between versions; a
        # report computed by an older Atlas must not survive an upgrade.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            calls, patcher = _counting_engine()
            with patcher:
                client.get("/policy?scope=all")
                first = len(calls)
                with patch("founderos_atlas.release.VERSION", "999.0.0"):
                    client.get("/policy?scope=all")
                self.assertGreater(
                    len(calls), first,
                    "a version change must re-evaluate",
                )


if __name__ == "__main__":
    unittest.main()
