"""PR-043.10 (POLISH) — product consistency, terminology, usability.

No new engines or architecture. These tests pin the operational-correctness
and consistency fixes: candidate/unused addresses never become operational
risks or health deductions; Advisor understands natural operational intent;
Compass consumes canonical devices only; prediction risk explains its
arithmetic; and terminology is consistent.
"""

from __future__ import annotations

import unittest

from founderos_atlas.advisor import router
from founderos_atlas.enterprise import DuplicateCandidate, SimilarityResult
from founderos_atlas.enterprise_intelligence import build_intelligence
from founderos_atlas.enterprise_intelligence.engine import IntelligenceEvidence
from founderos_atlas.prediction import ChangeRequest, predict
from founderos_atlas.prediction.risk import estimate_risk
from founderos_atlas.web.models import prediction_targets

from tests.test_evidence_correlation import discover_isp_lab

FIXED = "2026-07-13T00:00:00+00:00"


def _snapshot_with_stats(devices, *, unused, auth_failures=0):
    """A snapshot whose graph carries discovery statistics (a CIDR scan)."""

    return {
        "device_count": len(devices),
        "devices": [
            {
                "device_id": f"cisco-ios:{h}", "hostname": h,
                "management_ip": ip, "vendor": "cisco", "platform": "IOSv",
                "os_name": "IOS", "os_version": "15", "serial_number": None,
                "interfaces": [], "metadata": {},
            }
            for h, ip in devices
        ],
        "edges": [],
        "metadata": {
            "failed_hosts": [f"10.0.0.{i}" for i in range(100, 100 + unused)],
            "discovery_statistics": {
                "addresses_scanned": len(devices) + unused,
                "reachable": len(devices) + auth_failures,
                "authenticated": len(devices),
                "managed_devices": len(devices),
                "unused_addresses": unused,
                "authentication_failures": auth_failures,
                "unsupported_platforms": 0,
            },
        },
    }


# -- Parts 1/2/3: candidate addresses are never operational risks -----------------


class OperationalCorrectnessTests(unittest.TestCase):
    def test_unused_addresses_produce_no_top_risks(self) -> None:
        evidence = IntelligenceEvidence(
            generated_at=FIXED,
            snapshot=_snapshot_with_stats([("r1", "10.0.0.1")], unused=253),
            baseline_available=True,
        )
        report = build_intelligence(evidence)
        # No "Device unreachable" / discovery-failure findings from candidates.
        categories = {p.get("category") for p in report.to_dict()["priorities"]}
        self.assertNotIn("discovery-failure", categories)
        # And no unreachable-candidate health deduction.
        factor_names = {f["name"] for f in report.to_dict()["health"]["factors"]}
        self.assertNotIn("unreachable-devices", factor_names)

    def test_unused_addresses_do_not_tank_confidence(self) -> None:
        evidence = IntelligenceEvidence(
            generated_at=FIXED,
            snapshot=_snapshot_with_stats([("r1", "10.0.0.1")], unused=253),
            baseline_available=True,
        )
        # 253 unused of 254 scanned must NOT read as 99% discovery failure.
        health = build_intelligence(evidence).to_dict()["health"]
        self.assertIn(health["confidence"], ("high", "medium"))

    def test_authentication_failure_on_a_device_stays_a_risk(self) -> None:
        # A reachable device that failed auth IS an operational concern.
        evidence = IntelligenceEvidence(
            generated_at=FIXED,
            snapshot=_snapshot_with_stats(
                [("r1", "10.0.0.1")], unused=5, auth_failures=1
            ),
            failed_hosts=("10.0.0.8",),
            failed_details=(("10.0.0.8", "Authentication failed for 10.0.0.8"),),
            baseline_available=True,
        )
        categories = {
            p.get("category")
            for p in build_intelligence(evidence).to_dict()["priorities"]
        }
        self.assertIn("authentication-failure", categories)

    def test_unused_addresses_are_not_repeated_instability(self) -> None:
        """A CIDR scan re-attempts the same empty addresses every run; they
        must never be flagged as 'repeatedly unstable' devices (the
        recurring-instability health deduction / risk)."""

        from types import SimpleNamespace

        unused = [f"10.0.0.{i}" for i in range(100, 353)]
        records = tuple(
            SimpleNamespace(failures=tuple(unused), record_id=f"r{n}")
            for n in range(3)  # the same 253 unused addresses, three runs
        )
        evidence = IntelligenceEvidence(
            generated_at=FIXED,
            snapshot=_snapshot_with_stats([("r1", "10.0.0.1")], unused=253),
            failed_hosts=tuple(unused),
            recent_records=records,
            baseline_available=True,
        )
        # The recurring-instability signal (which drives the health
        # deduction and risk) excludes unused/candidate addresses entirely.
        self.assertEqual((), evidence.recurring_unstable_hosts)

    def test_recurring_instability_still_flags_genuine_auth_failures(self) -> None:
        from types import SimpleNamespace

        records = tuple(
            SimpleNamespace(failures=("10.0.0.8",), record_id=f"r{n}")
            for n in range(3)
        )
        evidence = IntelligenceEvidence(
            generated_at=FIXED,
            snapshot=_snapshot_with_stats(
                [("r1", "10.0.0.1")], unused=5, auth_failures=1
            ),
            failed_hosts=("10.0.0.8",),
            failed_details=(("10.0.0.8", "Authentication failed for 10.0.0.8"),),
            recent_records=records,
            baseline_available=True,
        )
        # A device that keeps failing AUTHENTICATION is genuine instability.
        self.assertEqual(("10.0.0.8",), evidence.recurring_unstable_hosts)

    def test_legacy_snapshot_without_statistics_keeps_unreachable_risk(self) -> None:
        # Backward compatibility: pre-043.8 snapshots still surface failures.
        evidence = IntelligenceEvidence(
            generated_at=FIXED,
            snapshot={
                "device_count": 1,
                "devices": [{"device_id": "x", "hostname": "r1",
                             "management_ip": "10.0.0.1", "vendor": "c",
                             "platform": "p", "os_name": "o", "os_version": "1",
                             "interfaces": [], "metadata": {}}],
                "edges": [],
                "metadata": {"failed_hosts": ["10.0.0.9"]},
            },
            failed_hosts=("10.0.0.9",),
            baseline_available=True,
        )
        categories = {
            p.get("category")
            for p in build_intelligence(evidence).to_dict()["priorities"]
        }
        self.assertIn("discovery-failure", categories)


# -- Part 4: Advisor natural-language intent --------------------------------------


class AdvisorIntentTests(unittest.TestCase):
    def test_operational_phrasings_map_to_health(self) -> None:
        for question in (
            "Is the network fine?",
            "Is everything healthy?",
            "Any issues?",
            "Anything critical?",
            "How is Delhi Lab?",
            "How healthy is the enterprise?",
            "Any risks?",
            "Is it okay?",
            "Should I worry about anything?",
        ):
            self.assertEqual(
                router.INTENT_HEALTH, router.classify(question), question
            )

    def test_specific_intents_still_win(self) -> None:
        # Polish must not swallow the other workflows.
        self.assertEqual(router.INTENT_CHANGES, router.classify("what changed today"))
        self.assertEqual(router.INTENT_SEARCH, router.classify("find core1"))
        self.assertEqual(router.INTENT_PATH, router.classify("path from a to b"))
        self.assertEqual(
            router.INTENT_PREDICTION, router.classify("predict shutdown of core1")
        )

    def test_health_question_answers_from_evidence_not_unknown(self) -> None:
        from founderos_atlas.advisor.engine import AdvisorContext, answer

        _r, _g, snapshot = discover_isp_lab()

        class _Graph:
            contributions = ()
            devices = True

        response = answer(
            "Is the network fine?",
            AdvisorContext(
                base_output_dir=__import__("pathlib").Path("."),
                profiles=(), graph=_Graph(), snapshot=snapshot.to_dict(),
                search_index=None, generated_at=FIXED,
            ),
        )
        self.assertEqual("health", response.intent)
        self.assertNotIn("enough evidence", response.summary.casefold())
        self.assertIn("managed device", response.summary.casefold())


# -- Part 5: Compass canonical device lists ---------------------------------------


class CompassCanonicalDeviceTests(unittest.TestCase):
    def test_duplicate_device_names_collapse_to_one(self) -> None:
        snapshot = {
            "devices": [
                {"device_id": "a:1", "hostname": "access1",
                 "management_ip": "10.0.0.1",
                 "interfaces": [{"name": "Gi0/1", "status": "up",
                                 "protocol_status": "up"}]},
                {"device_id": "a:2", "hostname": "access1",
                 "management_ip": "10.0.0.1",
                 "interfaces": [{"name": "Gi0/2", "status": "up",
                                 "protocol_status": "up"}]},
                {"device_id": "a:3", "hostname": "access1",
                 "management_ip": "10.0.0.1", "interfaces": []},
                {"device_id": "c:1", "hostname": "core1",
                 "management_ip": "10.0.0.9", "interfaces": []},
            ],
            "edges": [],
        }
        targets = prediction_targets(snapshot)
        hostnames = [t["hostname"] for t in targets]
        self.assertEqual(["access1", "core1"], hostnames)  # access1 once
        access1 = next(t for t in targets if t["hostname"] == "access1")
        # Interfaces from every observation are unioned, each once.
        self.assertEqual(
            ["Gi0/1", "Gi0/2"], [o["name"] for o in access1["interfaces"]]
        )


# -- Part 8: prediction risk explanation ------------------------------------------


class RiskExplanationTests(unittest.TestCase):
    def test_explanation_states_level_and_arithmetic(self) -> None:
        _r, _g, snapshot = discover_isp_lab()
        prediction = predict(
            ChangeRequest("t", "shutdown-interface", "isp1", "eth1", FIXED),
            snapshot=snapshot.to_dict(), generated_at=FIXED, fresh=True,
        )
        explanation = prediction.risk.explanation
        self.assertIn(prediction.risk.level, explanation)
        self.assertIn(str(prediction.risk.score), explanation)
        self.assertIn("because", explanation)
        # It rides in the serialized form too.
        self.assertEqual(explanation, prediction.risk.to_dict()["explanation"])

    def test_low_risk_explains_the_absence_of_factors(self) -> None:
        from founderos_atlas.prediction.risk import RiskAssessment

        assessment = RiskAssessment(level="low", score=0, factors=())
        self.assertIn("under 15", assessment.explanation)
        self.assertIn("no aggravating factors", assessment.explanation)

    def test_estimate_risk_low_case_still_explains(self) -> None:
        assessment = estimate_risk(
            critical_path_count=0,
            affected_device_count=0,
            carries_links=False,
            redundancy_verified=True,
        )
        self.assertEqual("low", assessment.level)
        self.assertIn("under 15", assessment.explanation)


# -- Part 6: terminology on duplicate actions -------------------------------------


class TerminologyTests(unittest.TestCase):
    def test_duplicate_candidate_offers_review_not_merge(self) -> None:
        candidate = DuplicateCandidate(
            left_profile_id="p1", left_profile_name="Delhi lab",
            right_profile_id="p2", right_profile_name="Delhi lab1",
            similarity=SimilarityResult(98, ("same serial number(s)",)),
        )
        actions = candidate.to_dict()["actions"]
        self.assertIn("review-duplicate", actions)
        self.assertNotIn("merge-later", actions)  # never "merge" in this PR


if __name__ == "__main__":
    unittest.main()
