"""Misleading-zero remediation (PR-178, Step 2).

The core rule: ZERO is a measurement; UNKNOWN / NOT YET OBSERVED is an
evidence state. These tests pin every direction of it — absence never
renders as 0 or 0%, a genuine zero never renders as an em-dash, the two
absent cases stay distinct (nothing evaluated vs evaluated-but-
unjudgeable), and unknown is slate, never green, never red.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world
from tests.test_profile_isolation import add_profile


def _fresh_app(tmp: Path):
    from founderos_atlas.web import create_app

    app = create_app(
        output_dir=tmp,
        history_root=tmp / ".atlas" / "history",
        workspace_root=tmp / "workspace",
    )
    app.config.update(TESTING=True)
    return app


class PolicyScoreBranchTests(unittest.TestCase):
    """CASE A (nothing evaluated) and CASE B (nothing judgeable) are
    different absences and must render differently."""

    def test_case_a_nothing_evaluated_reads_not_scored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _fresh_app(Path(tmp))
            page = app.test_client().get("/policy").get_data(as_text=True)
            self.assertIn(
                "Not scored — no configurations have been evaluated in "
                "this scope yet.", page,
            )
            self.assertNotIn("0%", page)
            # Reassurance is a judgement; none was made.
            self.assertNotIn(
                "No active failure or warning requires attention", page
            )
            # CASE B's words must not appear for CASE A: no evaluation
            # was attempted, so "not enough evidence" would overclaim.
            self.assertNotIn("Not enough evidence", page)

    def test_case_b_nothing_judgeable_reads_not_enough_evidence(self) -> None:
        # A genuine product state where evaluation happened but nothing
        # was JUDGED: a console-only device leaves 11 policies without
        # evidence, and its one deterministic failure (STD-SSH-001) is
        # covered by an audited exception — so every effective status is
        # missing-evidence or excepted, and judged == 0 with total > 0.
        from founderos_atlas.enterprise_memory import EnterpriseMemoryStore
        from founderos_atlas.policy.exceptions import PolicyExceptionRepository

        with tempfile.TemporaryDirectory() as tmp:
            app = _fresh_app(Path(tmp))
            profile = add_profile(
                app.config["ATLAS_PROFILE_SERVICE"], "Lab", "10.0.0.1"
            )
            store = EnterpriseMemoryStore(
                Path(tmp) / ".atlas" / "profiles" / profile.profile_id
                / "enterprise-memory"
            )
            store.store_evidence(
                device_id="dev-nocfg", hostname="nocfg",
                command="show clock", output=None,
                discovery_session="s1", transport="console",
            )
            PolicyExceptionRepository(Path(tmp) / "workspace").grant(
                policy_id="STD-SSH-001", hostname="nocfg",
                reason="console-only lab device", owner="ops",
            )
            page = app.test_client().get(
                f"/policy?scope={profile.profile_id}"
            ).get_data(as_text=True)
            self.assertIn("Not enough evidence", page)
            self.assertIn("produced no judgeable verdict", page)
            self.assertNotIn("0%", page)
            self.assertNotIn("Not scored —", page)

    def test_posture_score_returns_none_not_zero_when_unjudged(self) -> None:
        from founderos_atlas.policy.explorer import posture_score

        self.assertIsNone(posture_score({"pass": 0, "fail": 0})["score"])
        # Arithmetic unchanged when something WAS judged.
        self.assertEqual(
            50, posture_score({"pass": 1, "fail": 1})["score"]
        )
        # All-fail is a MEASURED zero and stays a number.
        self.assertEqual(
            0, posture_score({"pass": 0, "fail": 3})["score"]
        )

    def test_report_score_mirrors_the_page(self) -> None:
        from founderos_atlas.policy.models import PolicyReport
        from founderos_atlas.policy.packs import default_pack

        report = PolicyReport(
            pack=default_pack(), scope_label="Lab",
            generated_at="2026-08-12T10:00:00+00:00", evaluations=(),
        )
        self.assertIsNone(report.score)
        self.assertIsNone(report.to_dict()["score"])

    def test_trend_recorder_is_none_safe(self) -> None:
        from founderos_atlas.policy.trend import PolicyTrend

        with tempfile.TemporaryDirectory() as tmp:
            trend = PolicyTrend(tmp)
            recorded = trend.record(
                scope_id="s", recorded_at="2026-08-12T10:00:00+00:00",
                score=None, passed=0, failed=0, warnings=0, unknown=4,
            )
            self.assertTrue(recorded)
            self.assertIsNone(trend.series("s")[0]["score"])


class ChangesPartialComparisonTests(unittest.TestCase):
    def test_never_compared_says_so_instead_of_eight_zeros(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/changes?scope=all").get_data(as_text=True)
            self.assertIn(
                "Not compared — change detection needs two collections "
                "in this scope.", page,
            )
            # The old tile wall must not render its zeros.
            self.assertNotIn("<strong>Changes</strong><span>0</span>", page)
            self.assertNotIn("<strong>High severity</strong>", page)

    def test_one_discovery_is_still_not_a_comparison(self) -> None:
        # Even a DISCOVERED workspace has compared nothing after a
        # single run per profile — the honest banner stays until a
        # second collection exists.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/changes?scope=all").get_data(as_text=True)
            self.assertIn(
                "Not compared — change detection needs two collections",
                page,
            )

    def test_two_collections_render_measured_numbers(self) -> None:
        from datetime import timedelta

        from tests.test_federation import hyderabad_network
        from tests.test_profile_isolation import FIXED, run_discover

        with tempfile.TemporaryDirectory() as tmp:
            service, client = build_world(Path(tmp))
            run_discover(
                Path(tmp), service, hyderabad_network(), "Hyderabad",
                FIXED + timedelta(hours=1),
            )
            page = client.get("/changes?scope=all").get_data(as_text=True)
            self.assertNotIn(
                "Not compared — change detection needs two collections",
                page,
            )
            for kind in ("Topology", "Configuration", "Operational"):
                row = re.search(
                    rf"<strong>{kind}</strong><span>(.*?)</span>", page,
                    re.DOTALL,
                )
                self.assertIsNotNone(row, kind)
                cell = row.group(1).strip()
                self.assertTrue(
                    re.fullmatch(r"\d+", cell) or "Not compared" in cell,
                    f"{kind} rendered neither a measured number nor an "
                    f"honest absence: {cell!r}",
                )

    def test_compare_mode_names_the_unmeasured_kinds(self) -> None:
        # An on-demand comparison diffs two TOPOLOGY snapshots only:
        # configuration and operational were never measured for it, and
        # a bare cross-kind integer would silently claim they were.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/changes/compare").get_data(as_text=True)
            self.assertIn("(measured kinds)", page)
            self.assertIn("not compared", page)
            for kind in ("Configuration", "Operational"):
                row = re.search(
                    rf"<strong>{kind}</strong><span>(.*?)</span>", page,
                    re.DOTALL,
                )
                self.assertIsNotNone(row, kind)
                self.assertIn("Not compared", row.group(1))


class TimelineHonestyTests(unittest.TestCase):
    def test_fresh_workspace_shows_no_zero_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/timeline?scope=all").get_data(as_text=True)
            self.assertIn("No operational chronology yet", page)
            self.assertNotIn("<strong>Devices remembered</strong>", page)
            self.assertNotIn("<strong>Evidence records</strong>", page)
            self.assertNotIn(
                "<strong>Configuration changes</strong><span>0</span>", page
            )

    def test_discovered_workspace_keeps_the_chronology_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/timeline?scope=all").get_data(as_text=True)
            self.assertIn("<strong>Discoveries</strong>", page)
            # The inventory tiles moved to the pages that own them.
            self.assertNotIn("<strong>Devices remembered</strong>", page)
            self.assertNotIn("<strong>Configuration versions</strong>", page)

    def test_the_event_class_is_explicit_never_derived_from_absence(
        self,
    ) -> None:
        from founderos_atlas.audit import AuditEvent
        from founderos_atlas.web.chronicle import chronicle_events

        operator_mutation = AuditEvent.create(
            category="assignment", operation="create", subject="x",
            actor="mustafa", source="web",
        )
        machine_write = AuditEvent.create(
            category="workspace", operation="migrate",
            subject="workspace-schema:v2", actor="system",
        )
        events = chronicle_events(
            config_events=[], discovery_rows=[
                {"record_id": "r1", "started_at": "2026-08-12T10:00:00+00:00",
                 "profile_name": "Lab", "device_count": 2, "status": "completed"},
            ],
            change_rows=[], incident_reports=[], prediction_reports=[],
            compass_plans=[],
            audit_events=[operator_mutation, machine_write],
            policy_trend=[],
        )
        by_title = {e["title"]: e for e in events}
        machine = next(e for e in events if "workspace migrate" in e["title"])
        operator = next(e for e in events if "assignment create" in e["title"])
        self.assertTrue(machine["system"])
        self.assertFalse(operator["system"])
        # Every non-audit event keeps the default: chronology, not noise.
        discovery = next(e for e in events if e["kind"] == "discovery")
        self.assertFalse(discovery["system"])

    def test_an_unscored_trend_point_never_says_none_percent(self) -> None:
        from founderos_atlas.web.chronicle import chronicle_events

        events = chronicle_events(
            config_events=[], discovery_rows=[], change_rows=[],
            incident_reports=[], prediction_reports=[], compass_plans=[],
            audit_events=[],
            policy_trend=[("all", {
                "recorded_at": "2026-08-12T10:00:00+00:00", "score": None,
                "failed": 0, "warnings": 0, "unknown": 4,
            })],
        )
        title = events[0]["title"]
        self.assertNotIn("None%", title)
        self.assertIn("not scored", title)


class PathsPredictHonestyTests(unittest.TestCase):
    def test_paths_replaces_the_dead_form_with_the_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/paths?scope=all").get_data(as_text=True)
            self.assertNotIn("0 canonical device(s)", page)
            self.assertNotIn("0 contributing profile(s)", page)
            self.assertIn("No topology to investigate yet", page)
            self.assertIn("Run a discovery", page)
            # The instrument is replaced, not rendered dead.
            self.assertNotIn("Investigate Path</button>", page)

    def test_predict_never_claims_zero_canonical_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/predict?scope=all").get_data(as_text=True)
            self.assertNotIn("0 canonical device(s)", page)
            self.assertNotIn("0 contributing profile(s)", page)

    def test_unknown_tone_contract_in_the_templates(self) -> None:
        # Source contract, in the PR-174.1 style: the investigation
        # status badge maps its unknown branch to the slate unknown
        # badge — never the red "interrupted" class it used before.
        paths = Path(
            "src/founderos_atlas/web/templates/paths.html"
        ).read_text(encoding="utf-8")
        self.assertIn("hop-badge-unknown", paths)
        self.assertNotIn(
            "else 'interrupted'", paths,
            "the unknown investigation status is red again",
        )


if __name__ == "__main__":
    unittest.main()
