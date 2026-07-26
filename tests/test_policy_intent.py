"""Policy intent, applicability, baselines, calibration and prioritization."""

from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from founderos_atlas.policy import (
    INTENT_RECOMMENDED,
    Policy,
    PolicyApplicability,
    PolicyContext,
    PolicyEngine,
    PolicyPack,
    STARTER_PACK,
)
from founderos_atlas.policy.explorer import annotate_evaluations
from founderos_atlas.policy.governance import (
    PolicyGovernanceConflictError,
    PolicyGovernanceRepository,
    calibration_preview,
    effective_pack,
)
from founderos_atlas.policy.prioritization import (
    PolicyPostureHistory,
    prioritize,
    priority_score,
    priority_summary,
)
from founderos_atlas.policy.exceptions import PolicyExceptionRepository
from tests.test_enterprise_policy import FIXED_CLOCK, FRR_CONFIG, _seed_memory
from tests.test_investigation_scale import build_world, seed_policy_memory


class ApplicabilityTests(unittest.TestCase):
    def test_every_dimension_matches_and_exclusion_wins(self) -> None:
        selector = PolicyApplicability(
            platforms=("ios-*",),
            roles=("router",),
            sites=("delhi", "mumbai"),
            site_types=("datacenter",),
            tags=("critical",),
            profiles=("prod-*",),
            networks=("production",),
            environments=("prod",),
            include_devices=("edge-*",),
            exclude_devices=("edge-retired",),
        )
        context = PolicyContext(
            device_id="d1",
            hostname="edge-01",
            platform="IOS-XE",
            role="router",
            site="Delhi",
            site_type="datacenter",
            tags=("critical", "managed"),
            profile="prod-core",
            network="Production",
            environment="prod",
        )
        decision = selector.decide(context)
        self.assertTrue(decision.applicable)
        self.assertIn("platform", decision.explanation)
        excluded = selector.decide(replace(context, hostname="edge-retired"))
        self.assertFalse(excluded.applicable)
        self.assertIn("explicitly excluded", excluded.explanation)

    def test_unknown_targeted_attribute_is_not_guessed(self) -> None:
        selector = PolicyApplicability(roles=("firewall",))
        decision = selector.decide(PolicyContext("d1", "unknown"))
        self.assertFalse(decision.applicable)
        self.assertIn("role is unknown", decision.explanation)

    def test_policy_round_trip_and_legacy_defaults(self) -> None:
        original = replace(
            STARTER_PACK.policies[0],
            intent=INTENT_RECOMMENDED,
            applicability=PolicyApplicability(roles=("router",)),
        )
        self.assertEqual(
            original.to_dict(),
            Policy.from_dict(original.to_dict()).to_dict(),
        )
        legacy = original.to_dict()
        legacy.pop("intent")
        legacy.pop("applicability")
        loaded = Policy.from_dict(legacy)
        self.assertEqual("required", loaded.intent)
        self.assertTrue(loaded.applicability.universal)

    def test_pack_schema_rejects_duplicate_ids(self) -> None:
        policy = STARTER_PACK.policies[0]
        with self.assertRaisesRegex(ValueError, "unique"):
            PolicyPack(
                pack_id="duplicate",
                name="Duplicate",
                description="",
                version="1",
                author="test",
                policies=(policy, policy),
            )

    def test_engine_records_applicability_without_erasing_verdict(self) -> None:
        memory, _tmp = _seed_memory({"dev-core1": FRR_CONFIG})
        policy = replace(
            STARTER_PACK.policies[0],
            applicability=PolicyApplicability(roles=("firewall",)),
        )
        pack = replace(STARTER_PACK, policies=(policy,))
        report = PolicyEngine(pack, clock=lambda: FIXED_CLOCK).evaluate(
            memory,
            scope_label="Lab",
            device_contexts={
                "dev-core1": {
                    "hostname": "core1",
                    "role": "router",
                    "platform": "FRRouting",
                }
            },
        )
        evaluation = report.evaluations[0].to_dict()
        self.assertFalse(evaluation["applicability"]["applicable"])
        self.assertEqual("pass", evaluation["status"])
        rows = annotate_evaluations(
            [evaluation], now=FIXED_CLOCK
        )
        self.assertEqual("not-applicable", rows[0]["effective_status"])


class GovernanceTests(unittest.TestCase):
    def test_draft_does_not_apply_active_does_and_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = PolicyGovernanceRepository(tmp)
            policy_id = STARTER_PACK.policies[0].policy_id
            draft = repo.save(
                policy_id=policy_id,
                intent="recommended",
                applicability=PolicyApplicability(roles=("router",)),
                state="draft",
                owner="netops",
                reason="calibrating",
                actor="alice",
                expected_revision=0,
                occurred_at=FIXED_CLOCK,
            )
            self.assertEqual("draft", draft.state)
            self.assertEqual(
                "required",
                effective_pack(STARTER_PACK, repo.active()).policies[0].intent,
            )
            active = repo.save(
                policy_id=policy_id,
                intent="recommended",
                applicability=PolicyApplicability(roles=("router",)),
                state="active",
                owner="netops",
                reason="approved routing baseline",
                actor="bob",
                expected_revision=repo.revision(),
                occurred_at="2026-07-14T13:00:00+00:00",
            )
            effective = effective_pack(STARTER_PACK, repo.active())
            self.assertEqual("recommended", effective.policies[0].intent)
            self.assertEqual(("router",), effective.policies[0].applicability.roles)
            self.assertEqual(2, active.revision)
            audit = (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("policy-baseline", audit)
            self.assertIn("approved routing baseline", audit)

    def test_stale_catalog_revision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = PolicyGovernanceRepository(tmp)
            revision = repo.revision()
            repo.save(
                policy_id="P1",
                intent="required",
                applicability=PolicyApplicability(),
                state="draft",
                owner="alice",
                reason="test",
                actor="alice",
                expected_revision=revision,
            )
            with self.assertRaises(PolicyGovernanceConflictError):
                repo.check_revision(revision)

    def test_calibration_reports_broad_change_and_failures(self) -> None:
        evaluations = []
        for index in range(50):
            evaluations.append({
                "policy": {"policy_id": "P1"},
                "device_id": f"d{index}",
                "hostname": f"edge-{index}",
                "network": "Prod",
                "status": "fail",
                "applicability": {"applicable": False},
                "device_context": {
                    "device_id": f"d{index}",
                    "hostname": f"edge-{index}",
                    "role": "router",
                    "network": "Prod",
                },
            })
        preview = calibration_preview(
            evaluations,
            policy_id="P1",
            applicability=PolicyApplicability(roles=("router",)),
            intent="required",
        )
        self.assertEqual(50, preview["newly_applicable"])
        self.assertEqual(50, preview["projected_failures"])
        self.assertTrue(preview["broad_change"])
        self.assertEqual(64, len(preview["signature"]))

    def test_deviation_review_expiry_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = PolicyExceptionRepository(tmp)
            pending = repo.grant(
                policy_id="P1",
                hostname="edge",
                reason="awaiting risk owner",
                owner="netops",
                review_state="pending",
                expires_at="2026-08-01T00:00:00+00:00",
                occurred_at=FIXED_CLOCK,
            )
            self.assertFalse(pending.is_active(FIXED_CLOCK))
            approved = repo.grant(
                policy_id="P1",
                hostname="edge",
                reason="compensating control",
                owner="netops",
                review_state="approved",
                expires_at="2026-08-01T00:00:00+00:00",
                occurred_at=FIXED_CLOCK,
            )
            self.assertTrue(approved.is_active(FIXED_CLOCK))
            self.assertFalse(
                approved.is_active("2026-08-02T00:00:00+00:00")
            )
            with self.assertRaisesRegex(ValueError, "ISO"):
                repo.grant(
                    policy_id="P2",
                    hostname="edge",
                    reason="bad expiry",
                    owner="netops",
                    expires_at="next Tuesday",
                )


class PriorityTests(unittest.TestCase):
    def _row(self, *, fresh=True, regression=False):
        return {
            "subject": "policy-result:P1:edge",
            "effective_status": "fail",
            "policy": {
                "policy_id": "P1",
                "name": "AAA",
                "severity": "high",
            },
            "hostname": "edge",
            "intent": "required",
            "evidence_fresh": fresh,
            "is_new_regression": regression,
            "verdict_quality": "confirmed" if fresh else "provisional",
            "device_context": {
                "role": "firewall",
                "site_type": "datacenter",
            },
            "result": {"confidence": {"score": 0.95}},
        }

    def test_new_fresh_failure_outranks_stale(self) -> None:
        new = self._row(fresh=True, regression=True)
        stale = self._row(fresh=False, regression=False)
        self.assertGreater(priority_score(new), priority_score(stale))
        summary = priority_summary(prioritize([new, stale]))
        self.assertEqual(1, summary["new_regressions"])
        self.assertEqual(1, summary["confirmed_failures"])
        self.assertEqual(1, summary["stale_or_unverified"])

    def test_posture_history_only_marks_real_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = PolicyPostureHistory(tmp)
            base = [{**self._row(), "effective_status": "pass"}]
            self.assertFalse(history.compare_and_record(
                scope_id="all",
                source_revision="r1",
                rows=base,
                recorded_at=FIXED_CLOCK,
            ))
            failed = [self._row()]
            regressions = history.compare_and_record(
                scope_id="all",
                source_revision="r2",
                rows=failed,
                recorded_at="2026-07-14T13:00:00+00:00",
            )
            self.assertEqual(
                frozenset({"policy-result:P1:edge"}), regressions
            )
            self.assertEqual(
                regressions,
                history.compare_and_record(
                    scope_id="all",
                    source_revision="r2",
                    rows=failed,
                    recorded_at="2026-07-14T13:00:00+00:00",
                ),
            )


class PolicyBrowserContractTests(unittest.TestCase):
    def test_policy_page_and_calibration_preview_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_policy_memory(workdir)
            _app, client = build_world(workdir)
            page = client.get("/policy?scope=all").get_data(as_text=True)
            self.assertIn("Operational priorities", page)
            self.assertIn("Fresh confirmed findings", page)
            result_href = next(
                part.split('"')[0]
                for part in page.split('href="')[1:]
                if part.startswith("/policy/result/")
            )
            detail = client.get(result_href).get_data(as_text=True)
            self.assertIn("Policy intent and applicability", detail)

            policy_id = result_href.split("/")[3]
            preview = client.post("/policy/baselines/preview", data={
                "policy_id": policy_id,
                "intent": "required",
                "owner": "netops",
                "reason": "test preview",
                "roles": "router",
                "expected_revision": "0",
                "next": result_href,
            })
            self.assertEqual(200, preview.status_code)
            body = preview.get_data(as_text=True)
            self.assertIn("Policy calibration preview", body)
            self.assertIn("Nothing has been", body)

            saved = client.post("/policy/baselines", data={
                "policy_id": policy_id,
                "intent": "recommended",
                "owner": "netops",
                "reason": "approved scope",
                "roles": "router",
                "state": "draft",
                "expected_revision": "0",
                "next": result_href,
            })
            self.assertEqual(302, saved.status_code)
            repo = PolicyGovernanceRepository(workdir / "workspace")
            self.assertEqual("draft", repo.get(policy_id).state)
            self.assertEqual("recommended", repo.get(policy_id).intent)


if __name__ == "__main__":
    unittest.main()
