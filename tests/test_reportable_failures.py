"""Failures that can actually be reported (PR-180 Step 4).

Measured before this change: the bulk catch-all flashed an invented
cause with no identifier, logged nothing, and wrote no audit event —
the 302 hid it from the 500 handler, so support had nothing searchable;
the discovery-failed notification emitted /discovery?job=<id> while the
route read only ?profile= (a dead parameter that landed "Open source"
on an empty panel or a DIFFERENT job); and every branded error page
showed a correlation id, including 400/404/429 where the condition is
user-correctable and the id is noise.

The §8 rule now holds: an identifier is shown iff the failure is
internal-class AND Atlas can resolve it later.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_web_app import build_client, make_service


def _persist_jobs(workdir: Path, jobs: list[dict]) -> None:
    path = workdir / "out" / ".atlas" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")


def _job(job_id: str, status: str, completed_at: str) -> dict:
    return {
        "job_id": job_id, "profile_id": "hyderabad",
        "profile_name": "Hyderabad", "management_ip": "10.0.0.1",
        "status": status, "completed_at": completed_at,
        "message": f"Discovery {status}",
    }


class DiscoveryJobDeepLinkTests(unittest.TestCase):
    """The product emits /discovery?job=<id>; the route now honours it."""

    def _client(self, workdir: Path):
        _persist_jobs(workdir, [
            _job("aaaaaaaaaaaa", "failed", "2026-08-13T10:00:00+00:00"),
            _job("bbbbbbbbbbbb", "completed", "2026-08-14T10:00:00+00:00"),
        ])
        _, client = build_client(workdir, make_service(workdir))
        return client

    def test_a_valid_id_shows_exactly_that_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            # The OLDER failed job — precisely the notification case
            # where a later success would otherwise be substituted.
            body = client.get("/discovery?job=aaaaaaaaaaaa").get_data(
                as_text=True
            )
            self.assertIn('data-job-id="aaaaaaaaaaaa"', body)
            self.assertNotIn('data-job-id="bbbbbbbbbbbb"', body)

    def test_an_unknown_wellformed_id_says_so_and_substitutes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            body = client.get(
                "/discovery?job=cccccccccccc", follow_redirects=True
            ).get_data(as_text=True)
            self.assertIn("no longer in this Atlas", body)
            self.assertNotIn('data-job-id="', body)

    def test_a_malformed_id_is_treated_as_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            for bad in ("DROP TABLE", "abc", "g" * 12, "a" * 13, "../etc"):
                response = client.get(f"/discovery?job={bad}")
                self.assertEqual(200, response.status_code, bad)
                body = response.get_data(as_text=True)
                self.assertNotIn("no longer in this Atlas", body, bad)


class BulkInternalFailureTests(unittest.TestCase):
    """The discovery INTERNAL contract — log the detail, hand the
    operator a resolvable id — finally applies to /changes/bulk."""

    class _Plan:
        def counts(self):
            return {"updated": 1}

    def test_the_failure_is_logged_and_the_flash_carries_the_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            with patch("founderos_atlas.change.bulk.classify",
                       return_value=self._Plan()), \
                    patch("founderos_atlas.change.bulk.execute",
                          side_effect=RuntimeError(
                              "boom password=SuperSecret123"
                          )), \
                    self.assertLogs("atlas", level=logging.ERROR) as logs:
                response = client.post("/changes/bulk", data={
                    "bulk_action": "acknowledge",
                    "subjects": ["change:v2:lab:deadbeefdeadbeef"],
                    "next": "/changes",
                }, follow_redirects=True)
            body = response.get_data(as_text=True)
            self.assertIn("The bulk action failed and nothing was changed",
                          body)
            self.assertIn("Quote req-", body)
            self.assertIn("when reporting this", body)
            # The old copy invented a cause; only the
            # WorkspaceCorruptedError branch may name one.
            self.assertNotIn("audit record could not be written", body)
            # The foreign exception text stays out of the page…
            self.assertNotIn("SuperSecret123", body)
            self.assertNotIn("boom", body)
            # …and the detail went to the log, under the same id.
            joined = "\n".join(logs.output)
            self.assertIn("bulk change action failed correlation=req-",
                          joined)

    def test_json_log_lines_carry_the_class_name_never_the_text(self) -> None:
        # The property the flash's safety rests on: JsonLineFormatter
        # emits the exception CLASS NAME only — no traceback, no
        # message text (which can carry secrets) — so logging the
        # detail can never leak it into the structured stream.
        from founderos_atlas.web.observability import JsonLineFormatter

        record = logging.LogRecord(
            name="atlas", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="bulk change action failed correlation=req-abc", args=(),
            exc_info=None,
        )
        try:
            raise RuntimeError("password=SuperSecret123 at C:\\private")
        except RuntimeError:
            import sys

            record.exc_info = sys.exc_info()
        line = JsonLineFormatter().format(record)
        self.assertIn('"exception": "RuntimeError"', line)
        self.assertNotIn("SuperSecret123", line)
        self.assertNotIn("Traceback", line)
        self.assertNotIn("private", line)


class CorrelationIdVisibilityTests(unittest.TestCase):
    """§8: 400/404 hide the id; 500 shows it and says to quote it."""

    def test_a_404_wastes_no_time_on_an_irrelevant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            body = client.get("/no-such-page").get_data(as_text=True)
            self.assertNotIn("Correlation id", body)

    def test_a_400_wastes_no_time_on_an_irrelevant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            response = client.post(
                "/prism/playground/export", data={"format": "exe"},
            )
            self.assertEqual(400, response.status_code)
            self.assertNotIn("Correlation id",
                             response.get_data(as_text=True))

    def test_a_500_still_hands_over_a_resolvable_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            app, client = build_client(workdir, make_service(workdir))
            app.config.update(PROPAGATE_EXCEPTIONS=False)
            with patch(
                "founderos_atlas.web.system_info.collect_system_information",
                side_effect=RuntimeError("boom"),
            ):
                response = client.get("/settings")
            self.assertEqual(500, response.status_code)
            body = response.get_data(as_text=True)
            self.assertIn("Correlation id", body)
            self.assertIn("Quote the", body)


if __name__ == "__main__":
    unittest.main()
