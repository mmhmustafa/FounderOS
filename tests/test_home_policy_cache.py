"""Home policy-summary cache (audit-2 #10).

Home's canonical health runs the policy engine, which re-reads the whole
evidence store — ~4.4 s against a real workspace. The cache keys on a
fingerprint of the store's mutable index files, so warm renders skip the
evaluation while ANY evidence write deterministically invalidates it.
The cached value is derived workspace data identical for every operator;
nothing user-specific enters the evaluation or the cache key.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from founderos_atlas.policy import PolicyEngine

from tests.test_polish import build_world


class PolicySummaryCacheTests(unittest.TestCase):
    def _counting_engine(self):
        calls = []
        original = PolicyEngine.evaluate_scopes

        def counted(self, *args, **kwargs):
            calls.append(1)
            return original(self, *args, **kwargs)

        return calls, patch.object(PolicyEngine, "evaluate_scopes", counted)

    def test_warm_home_skips_re_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            calls, patcher = self._counting_engine()
            with patcher:
                self.assertEqual(client.get("/?scope=all").status_code, 200)
                first = len(calls)
                self.assertEqual(client.get("/?scope=all").status_code, 200)
                self.assertEqual(
                    len(calls), first,
                    "an unchanged evidence store must not re-evaluate",
                )

    def test_evidence_write_invalidates_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            calls, patcher = self._counting_engine()
            with patcher:
                client.get("/?scope=all")
                first = len(calls)
                # Any store write updates an index file's stamp.
                touched = 0
                for records in Path(tmp).glob(
                    "**/enterprise-memory/evidence/records.json"
                ):
                    stamp = records.stat()
                    os.utime(
                        records,
                        ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000),
                    )
                    touched += 1
                self.assertGreater(touched, 0, "no evidence store found")
                client.get("/?scope=all")
                self.assertGreater(
                    len(calls), first,
                    "a changed evidence store must re-evaluate",
                )


if __name__ == "__main__":
    unittest.main()
