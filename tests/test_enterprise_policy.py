"""PR-047 (SENTINEL) — Enterprise Policy Engine + CORTEX kernel acceptance tests.

Atlas's first application built on the reasoning framework. These tests pin the
Part 11 checklist — policy model, packs, rule execution, reasoning integration,
evidence retrieval, confidence calculation, explainability, categories, result
schema — and the two guarantees that make the layer trustworthy:

1. **The kernel changes no conclusion.** The CORTEX calculus reproduces
   ``root_cause.calculate`` byte-for-byte (the characterisation proof from
   REASONING_ENGINE §6 — the evidence the extraction is safe).
2. **A verdict is never guessed and never leaks a secret.** Missing evidence
   yields band ``unknown``; a rendered result never contains a password.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from founderos_atlas.enterprise_memory import (
    DiscoverySession,
    EnterpriseMemory,
    EnterpriseMemoryStore,
)
from founderos_atlas.reasoning import (
    BAND_HIGH,
    BAND_LOW,
    BAND_MEDIUM,
    BAND_UNKNOWN,
    BAND_VERY_HIGH,
    CONFIDENCE_CAP,
    CONFIDENCE_FLOOR,
    Confidence,
    Evidence,
    EvidenceGap,
    QUESTION_COMPLY,
    ReasoningEngine,
    ReasoningQuestion,
    ReasoningResult,
    RuleRegistry,
    assess,
    band,
    clamp,
    contradiction,
    corroboration,
    direct_observation,
    staleness,
)
from founderos_atlas.reasoning.evidence import STRENGTH_DIRECT
from founderos_atlas.policy import (
    CATEGORIES,
    PolicyEngine,
    PolicyRule,
    STARTER_PACK,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_UNKNOWN,
)
from founderos_atlas.policy.matcher import (
    OP_ALL_PRESENT,
    OP_ANY_PRESENT,
    OP_CONDITIONAL_PRESENT,
    OP_INTERFACES_SHUTDOWN,
    OP_NONE_PRESENT,
    MATCH_REGEX,
    PolicyCheck,
    evaluate_check,
)

from founderos_atlas.root_cause import confidence as root_cause_confidence


FRR_CONFIG = (
    "frr version 8.4\n"
    "hostname core1\n"
    "log syslog informational\n"
    "!\n"
    "interface lo\n"
    " ip address 10.0.0.1/32\n"
    "!\n"
    "interface eth1\n"
    " description uplink\n"
    " ip address 10.1.1.1/30\n"
    "!\n"
    "interface eth2\n"
    "!\n"
    "router bgp 65100\n"
    " bgp router-id 10.0.0.1\n"
    " neighbor 10.1.1.2 remote-as 65200\n"
    "!\n"
    "router ospf\n"
    " ospf router-id 10.0.0.1\n"
    "!\n"
)

SECRET_CONFIG = (
    "hostname secret1\n"
    "snmp-server community SUPERSECRET RO\n"
    "username admin secret 0 HUNTER2\n"
    "interface lo\n"
    " ip address 10.0.0.2/32\n"
    "!\n"
)

FIXED_CLOCK = "2026-07-14T12:00:00+00:00"


def _seed_memory(configs: dict[str, str]) -> tuple[EnterpriseMemory, Path]:
    """An Enterprise Memory seeded with one config per device_id."""

    tmp = Path(tempfile.mkdtemp())
    store = EnterpriseMemoryStore(tmp / "enterprise-memory")
    store.begin_session(
        DiscoverySession(
            session_id="sess-1",
            network="Lab",
            profile_id="p1",
            profile_name="Lab",
            started_at="2026-07-14T10:00:00+00:00",
        )
    )
    for device_id, config in configs.items():
        hostname = device_id.replace("dev-", "")
        store.store_evidence(
            device_id=device_id,
            hostname=hostname,
            command="show running-config",
            output=config,
            discovery_session="sess-1",
            transport="ssh",
            platform="FRRouting",
        )
        if config is not None:
            store.store_configuration(
                device_id=device_id,
                hostname=hostname,
                discovery_session="sess-1",
                running_config=config,
                platform="FRRouting",
            )
    return EnterpriseMemory(store), tmp


# -- Part: the confidence calculus (kernel) ----------------------------------


class ConfidenceCalculusTests(unittest.TestCase):
    def test_reproduces_root_cause_byte_for_byte(self) -> None:
        """The characterisation proof: the new calculus must reproduce the most
        complete existing scorer exactly, or the extraction is not safe."""

        cases = [
            dict(base=0.60, supporting=2, contradicting=1, interface_match=True, stale=True),
            dict(base=0.50, supporting=3, contradicting=0, interface_match=False, stale=False),
            dict(base=0.70, supporting=0, contradicting=2, interface_match=True, stale=False),
            dict(base=0.40, supporting=5, contradicting=0, interface_match=False, stale=True),
        ]
        for case in cases:
            expected = root_cause_confidence.calculate(
                case["base"],
                supporting=case["supporting"],
                contradicting=case["contradicting"],
                interface_match=case["interface_match"],
                stale=case["stale"],
            )
            factors = []
            if case["interface_match"]:
                factors.append(direct_observation("interface match"))
            if case["supporting"]:
                factors.append(corroboration(case["supporting"], "supporting"))
            if case["contradicting"]:
                factors.append(contradiction(case["contradicting"], "contradicting"))
            if case["stale"]:
                factors.append(staleness("stale"))
            got = assess(case["base"], factors)
            self.assertAlmostEqual(expected, got.score, places=9, msg=case)
            self.assertEqual(root_cause_confidence.band(expected), got.band, msg=case)

    def test_bounds_are_never_exceeded(self) -> None:
        self.assertEqual(CONFIDENCE_CAP, clamp(5.0))
        self.assertEqual(CONFIDENCE_FLOOR, clamp(-5.0))

    def test_band_thresholds(self) -> None:
        self.assertEqual(BAND_VERY_HIGH, band(0.90))
        self.assertEqual(BAND_HIGH, band(0.72))
        self.assertEqual(BAND_MEDIUM, band(0.50))
        self.assertEqual(BAND_LOW, band(0.49))

    def test_no_evidence_is_unknown_not_low(self) -> None:
        c = assess(0.9, [direct_observation("x")], has_evidence=False)
        self.assertEqual(BAND_UNKNOWN, c.band)
        self.assertEqual(CONFIDENCE_FLOOR, c.score)
        self.assertEqual(BAND_UNKNOWN, Confidence.unknown().band)

    def test_corroboration_is_capped(self) -> None:
        # 3 and 10 corroborating sources price identically (diminishing, capped).
        self.assertEqual(corroboration(3, "").points, corroboration(10, "").points)

    def test_factor_weights_are_contract_not_caller_supplied(self) -> None:
        # A contradiction is worth exactly -0.15; the caller cannot change it.
        self.assertAlmostEqual(-0.15, contradiction(1, "").points)
        self.assertAlmostEqual(0.15, direct_observation("").points)


# -- Part: evidence + result schema round-trips ------------------------------


class SchemaTests(unittest.TestCase):
    def test_evidence_round_trip(self) -> None:
        ev = Evidence(
            id="config:abc", kind="running-config", source="cli",
            subject="dev-1", strength=STRENGTH_DIRECT, text="hostname x",
        )
        self.assertEqual(ev.to_dict(), Evidence.from_dict(ev.to_dict()).to_dict())

    def test_confidence_round_trip(self) -> None:
        c = assess(0.7, [direct_observation("x")])
        self.assertEqual(c.to_dict(), Confidence.from_dict(c.to_dict()).to_dict())

    def test_result_carries_all_nine_concepts(self) -> None:
        memory, _tmp = _seed_memory({"dev-core1": FRR_CONFIG})
        engine = PolicyEngine(clock=lambda: FIXED_CLOCK)
        report = engine.evaluate(memory, scope_label="Lab")
        result = report.evaluations[0].result
        d = result.to_dict()
        for key in (
            "conclusion", "conclusion_kind", "confidence", "severity",
            "evidence_used", "evidence_missing", "reasoning_path",
            "alternatives_rejected", "recommendations", "generated_at",
            "as_of", "provenance",
        ):
            self.assertIn(key, d)
        # confidence is always score AND band (fixes Advisor's lossy str)
        self.assertIn("score", d["confidence"])
        self.assertIn("band", d["confidence"])


# -- Part: rule framework + engine -------------------------------------------


class EngineTests(unittest.TestCase):
    def test_registry_is_enumerable_and_focusable(self) -> None:
        registry = RuleRegistry()
        registry.register_all(PolicyRule(p) for p in STARTER_PACK.policies)
        self.assertEqual(len(STARTER_PACK.policies), len(registry))
        focused = registry.for_question(QUESTION_COMPLY, focus="STD-HOST-001")
        self.assertEqual(1, len(focused))
        self.assertEqual("STD-HOST-001", focused[0].rule_id)

    def test_engine_reports_unknown_when_no_rule_matches(self) -> None:
        registry = RuleRegistry()  # empty
        engine = ReasoningEngine(registry, (), clock=lambda: FIXED_CLOCK)
        result = engine.evaluate(
            ReasoningQuestion(kind=QUESTION_COMPLY, subject="dev-x")
        )
        self.assertEqual("unknown", result.conclusion_kind)
        self.assertEqual(BAND_UNKNOWN, result.confidence.band)


# -- Part: the matcher operators ---------------------------------------------


class MatcherTests(unittest.TestCase):
    def test_any_present(self) -> None:
        c = PolicyCheck(evidence="running-config", operator=OP_ANY_PRESENT, patterns=("hostname",))
        self.assertTrue(evaluate_check(c, FRR_CONFIG).matched)
        self.assertFalse(evaluate_check(c, "no name here").matched)

    def test_all_present_reports_missing(self) -> None:
        c = PolicyCheck(
            evidence="running-config", operator=OP_ALL_PRESENT,
            patterns=("hostname", "aaa new-model"),
        )
        report = evaluate_check(c, FRR_CONFIG)
        self.assertFalse(report.matched)
        self.assertIn("aaa new-model", report.missing_patterns)

    def test_none_present(self) -> None:
        c = PolicyCheck(evidence="running-config", operator=OP_NONE_PRESENT, patterns=("telnet",))
        self.assertTrue(evaluate_check(c, FRR_CONFIG).matched)
        self.assertFalse(evaluate_check(c, "transport input telnet").matched)

    def test_conditional_present_not_applicable_without_antecedent(self) -> None:
        c = PolicyCheck(
            evidence="running-config", operator=OP_CONDITIONAL_PRESENT,
            antecedent=(r"router bgp\s+\d+",), patterns=(r"bgp router-id\s+\S+",),
            match=MATCH_REGEX,
        )
        # config with BGP + router-id: applicable + matched
        applicable = evaluate_check(c, FRR_CONFIG)
        self.assertTrue(applicable.applicable)
        self.assertTrue(applicable.matched)
        # config without BGP: not applicable (never a failure)
        na = evaluate_check(c, "hostname x\n")
        self.assertFalse(na.applicable)
        self.assertTrue(na.matched)

    def test_interfaces_shutdown_flags_unused_up_interface(self) -> None:
        c = PolicyCheck(evidence="running-config", operator=OP_INTERFACES_SHUTDOWN)
        report = evaluate_check(c, FRR_CONFIG)
        # eth2 is up, unaddressed, undescribed -> a violation; eth1 & lo are fine
        self.assertFalse(report.matched)
        self.assertTrue(any("eth2" in h.text for h in report.hits))


# -- Part: policy model + packs ----------------------------------------------


class PolicyModelTests(unittest.TestCase):
    def test_policy_round_trip(self) -> None:
        policy = STARTER_PACK.policies[0]
        from founderos_atlas.policy.models import Policy

        self.assertEqual(policy.to_dict(), Policy.from_dict(policy.to_dict()).to_dict())

    def test_starter_pack_covers_multiple_categories(self) -> None:
        used = set(STARTER_PACK.categories())
        self.assertGreaterEqual(len(used), 5)
        for category in used:
            self.assertIn(category, CATEGORIES)

    def test_every_policy_declares_remediation_and_expected_state(self) -> None:
        for policy in STARTER_PACK.policies:
            self.assertTrue(policy.expected_state, policy.policy_id)
            self.assertTrue(policy.recommendation, policy.policy_id)
            self.assertTrue(policy.remediation, policy.policy_id)


# -- Part: end-to-end policy evaluation (reasoning integration) --------------


class PolicyEvaluationTests(unittest.TestCase):
    def _report(self, configs):
        memory, _tmp = _seed_memory(configs)
        engine = PolicyEngine(clock=lambda: FIXED_CLOCK)
        return engine.evaluate(memory, scope_label="Lab")

    def test_frr_device_produces_expected_dispositions(self) -> None:
        report = self._report({"dev-core1": FRR_CONFIG})
        by_policy = {e.policy.policy_id: e for e in report.evaluations}
        # Present in FRR config / observed transport -> pass
        for pid in ("STD-SSH-001", "STD-HOST-001", "STD-LOG-001",
                    "STD-LOOP-001", "STD-BGPRID-001", "STD-OSPFRID-001"):
            self.assertEqual(STATUS_PASSED, by_policy[pid].status, pid)
        # Not expressed in FRR config -> fail (honest, evidence-based)
        for pid in ("STD-AAA-001", "STD-NTP-001", "STD-SNMP-001", "STD-DOMAIN-001"):
            self.assertEqual(STATUS_FAILED, by_policy[pid].status, pid)

    def test_missing_config_is_unknown_never_guessed(self) -> None:
        # A device with evidence but no configuration snapshot: a
        # config-required policy must report Unknown, never guess a verdict.
        from founderos_atlas.enterprise_memory import EnterpriseMemoryStore
        tmp = Path(tempfile.mkdtemp())
        s = EnterpriseMemoryStore(tmp / "m")
        s.begin_session(DiscoverySession(session_id="s", network="L", profile_id="p",
                                         profile_name="L", started_at="2026-07-14T10:00:00+00:00"))
        s.store_evidence(device_id="dev-nocfg", hostname="nocfg", command="show version",
                         output="v", discovery_session="s", transport="ssh")
        mem = EnterpriseMemory(s)
        engine = PolicyEngine(clock=lambda: FIXED_CLOCK)
        host = next(p for p in STARTER_PACK.policies if p.policy_id == "STD-HOST-001")
        ev = engine.evaluate_device(mem, "dev-nocfg", host, scope_label="L")
        self.assertEqual(STATUS_UNKNOWN, ev.status)
        self.assertEqual(BAND_UNKNOWN, ev.result.confidence.band)
        self.assertTrue(ev.result.evidence_missing)

    def test_score_excludes_unknown_from_denominator(self) -> None:
        report = self._report({"dev-core1": FRR_CONFIG})
        # judged = passed + failed + warnings; unknown excluded
        self.assertEqual(report.judged, report.passed + report.failed + report.warnings)
        expected = int(round(100 * report.passed / report.judged))
        self.assertEqual(expected, report.score)

    def test_failure_is_always_explained(self) -> None:
        report = self._report({"dev-core1": FRR_CONFIG})
        for e in report.evaluations:
            if e.status == STATUS_FAILED:
                self.assertTrue(e.result.reasoning_path, e.policy.policy_id)
                self.assertTrue(e.result.recommendations, e.policy.policy_id)
                self.assertTrue(e.result.evidence_used, e.policy.policy_id)
                # a rejected alternative is recorded (why not "compliant"?)
                self.assertTrue(e.result.alternatives_rejected, e.policy.policy_id)

    def test_pass_carries_direct_observation_and_high_band(self) -> None:
        report = self._report({"dev-core1": FRR_CONFIG})
        host = next(e for e in report.evaluations if e.policy.policy_id == "STD-HOST-001")
        self.assertEqual(STATUS_PASSED, host.status)
        self.assertIn(host.result.confidence.band, (BAND_HIGH, BAND_VERY_HIGH))
        names = {f.name for f in host.result.confidence.factors}
        self.assertIn("direct-observation", names)

    def test_result_never_contains_a_secret(self) -> None:
        report = self._report({"dev-secret1": SECRET_CONFIG})
        blob = str(report.to_dict())
        self.assertNotIn("SUPERSECRET", blob)
        self.assertNotIn("HUNTER2", blob)
        # ...but the policy still evaluated (hostname present -> pass)
        host = next(e for e in report.evaluations if e.policy.policy_id == "STD-HOST-001")
        self.assertEqual(STATUS_PASSED, host.status)

    def test_determinism_same_inputs_same_verdicts(self) -> None:
        a = self._report({"dev-core1": FRR_CONFIG})
        b = self._report({"dev-core1": FRR_CONFIG})
        self.assertEqual(
            [(e.policy.policy_id, e.status, e.result.confidence.score) for e in a.evaluations],
            [(e.policy.policy_id, e.status, e.result.confidence.score) for e in b.evaluations],
        )

    def test_modifying_config_changes_the_verdict(self) -> None:
        # The manual-validation invariant: fix the gap, the policy flips.
        before = self._report({"dev-core1": FRR_CONFIG})
        ntp_before = next(e for e in before.evaluations if e.policy.policy_id == "STD-NTP-001")
        self.assertEqual(STATUS_FAILED, ntp_before.status)
        after = self._report({"dev-core1": FRR_CONFIG + "ntp server 10.0.0.254\n"})
        ntp_after = next(e for e in after.evaluations if e.policy.policy_id == "STD-NTP-001")
        self.assertEqual(STATUS_PASSED, ntp_after.status)


if __name__ == "__main__":
    unittest.main()
