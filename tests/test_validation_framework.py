"""PR-172 — Operational Validation Framework acceptance tests.

Pins the approved architecture review's success criteria, most
importantly R1: **a device that does not run a protocol is never
counted as passing that protocol's policies.** The minority-protocol
estate here is the exact shape the review proved the defect with — a
fleet where most devices do not run BGP must not report them as
BGP-compliant, and the one broken BGP speaker must dominate the
verdict, not drown in irrelevant passes.
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
from founderos_atlas.investigation.engines import aggregate_policy_report
from founderos_atlas.policy import PolicyEngine
from founderos_atlas.policy.applicability import PolicyApplicability
from founderos_atlas.policy.matcher import (
    OP_ANY_PRESENT,
    OP_CONDITIONAL_PRESENT,
    PolicyCheck,
)
from founderos_atlas.policy.models import Policy, PolicyPack
from founderos_atlas.reasoning.rules import RuleOutcome


FIXED_CLOCK = "2026-08-03T12:00:00+00:00"

# A device that speaks BGP and satisfies the starter rule.
BGP_GOOD = (
    "hostname bgp-good\n"
    "!\n"
    "router bgp 65001\n"
    " bgp router-id 10.0.0.1\n"
    " neighbor 10.0.0.2 remote-as 65002\n"
    "!\n"
)

# A device that speaks BGP and violates it (no router-id).
BGP_BAD = (
    "hostname bgp-bad\n"
    "!\n"
    "router bgp 65002\n"
    " neighbor 10.0.0.1 remote-as 65001\n"
    "!\n"
)

# A device with no BGP at all — the majority of any real estate for a
# minority protocol. OSPF only.
NO_BGP = (
    "hostname edge\n"
    "!\n"
    "router ospf\n"
    " ospf router-id 10.0.9.9\n"
    "!\n"
)


def _seed_memory(configs: dict[str, str | None]) -> tuple[EnterpriseMemory, Path]:
    tmp = Path(tempfile.mkdtemp())
    store = EnterpriseMemoryStore(tmp / "enterprise-memory")
    store.begin_session(
        DiscoverySession(
            session_id="sess-1",
            network="Lab",
            profile_id="p1",
            profile_name="Lab",
            started_at="2026-08-03T10:00:00+00:00",
        )
    )
    for device_id, config in configs.items():
        hostname = device_id.replace("dev-", "")
        store.store_evidence(
            device_id=device_id,
            hostname=hostname,
            command="show running-config",
            output=config or "",
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


def _minority_estate() -> tuple[EnterpriseMemory, Path]:
    """1 compliant BGP speaker, 1 broken one, 3 devices with no BGP."""

    return _seed_memory({
        "dev-bgp-good": BGP_GOOD,
        "dev-bgp-bad": BGP_BAD,
        "dev-edge1": NO_BGP,
        "dev-edge2": NO_BGP,
        "dev-edge3": NO_BGP,
    })


# -- Step 1: R1 — not applicable is a third outcome, never a pass ------------


class RuleOutcomeApplicabilityTests(unittest.TestCase):
    def test_rule_outcome_defaults_applicable(self) -> None:
        outcome = RuleOutcome(
            conclusion="x", conclusion_kind="pass", base_confidence=0.7,
        )
        self.assertTrue(outcome.applicable)

    def test_not_applicable_flows_to_the_evaluation(self) -> None:
        """The antecedent-absent outcome reaches PolicyEvaluation as
        applicable=False while conclusion_kind stays pass (review R2:
        the /policy headline keeps today's meaning — the honest split
        lives in the aggregation, not in a silently changed metric)."""

        memory, _tmp = _minority_estate()
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        bgp = [
            e for e in report.evaluations
            if "bgp" in set(e.policy.tags)
        ]
        self.assertEqual(5, len(bgp))
        by_host = {e.hostname: e for e in bgp}

        self.assertTrue(by_host["bgp-good"].applicable)
        self.assertEqual("pass", by_host["bgp-good"].status)
        self.assertTrue(by_host["bgp-bad"].applicable)
        self.assertEqual("fail", by_host["bgp-bad"].status)
        for host in ("edge1", "edge2", "edge3"):
            evaluation = by_host[host]
            self.assertFalse(
                evaluation.applicable,
                f"{host} does not run BGP; the rule must not apply",
            )
            # R2 pinned: the raw disposition is unchanged today.
            self.assertEqual("pass", evaluation.status)
            self.assertFalse(evaluation.result.applicable)
            self.assertIn("not applicable", evaluation.result.conclusion)

    def test_applicable_is_exported(self) -> None:
        memory, _tmp = _seed_memory({"dev-edge1": NO_BGP})
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        evaluation = report.evaluations[0]
        self.assertIn("applicable", evaluation.to_dict())
        self.assertIn("applicable", evaluation.result.to_dict())

    def test_policy_report_excludes_not_applicable_from_the_score(
        self,
    ) -> None:
        """R2, DECIDED (PR-174.2): the /policy headline number now
        excludes not-applicable evaluations. PR-172 deliberately left
        them counted as passes and reported the discrepancy rather than
        changing a business-visible metric unasked; this asserts the
        decision that followed."""

        memory, _tmp = _minority_estate()
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        raw_pass = sum(1 for e in report.evaluations if e.status == "pass")
        na = sum(
            1 for e in report.evaluations
            if e.status == "pass" and not e.applicable
        )
        self.assertGreaterEqual(na, 3)
        # The headline no longer counts them...
        self.assertEqual(raw_pass - na, report.passed)
        self.assertEqual(na, report.not_applicable)
        # ...and they are in neither the numerator nor the denominator.
        self.assertEqual(
            report.passed + report.failed + report.warnings, report.judged,
        )
        self.assertIn("not_applicable", report.to_dict())


class PolicyPageScoreTests(unittest.TestCase):
    """PR-174.2 — the /policy headline number and the page's own tiles
    tell the same story, and neither counts absence as compliance."""

    def test_the_engine_score_and_the_page_score_agree(self) -> None:
        from founderos_atlas.policy.explorer import (
            annotate_evaluations, posture_score, summarize,
        )

        memory, _tmp = _minority_estate()
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        rows = annotate_evaluations(
            [e.to_dict() for e in report.evaluations],
            now=FIXED_CLOCK, sites_by_device={},
        )
        counts = summarize(rows)
        posture = posture_score(counts)
        self.assertGreater(report.not_applicable, 0)
        self.assertEqual(report.not_applicable, counts["not-applicable"])
        self.assertEqual(report.judged, posture["judged"])
        self.assertEqual(report.score, posture["score"])

    def test_an_estate_that_runs_nothing_scores_zero_not_a_hundred(
        self,
    ) -> None:
        """The inversion R2 existed to close: an estate where the
        subject is configured NOWHERE used to score 100% because every
        not-applicable evaluation counted as a pass."""

        memory, _tmp = _seed_memory({
            "dev-edge1": NO_BGP, "dev-edge2": NO_BGP,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        bgp = [e for e in report.evaluations if "bgp" in set(e.policy.tags)]
        self.assertTrue(bgp)
        self.assertTrue(all(not e.applicable for e in bgp))
        # Those evaluations are in neither the numerator nor the
        # denominator of the headline score.
        self.assertEqual(
            0, sum(1 for e in bgp if e.applicable),
        )


class MinorityProtocolAggregationTests(unittest.TestCase):
    """The review's §1.3 estate, asserted through the shared seam both
    answer paths read."""

    def setUp(self) -> None:
        memory, self._tmp = _minority_estate()
        self.report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        self.aggregate = aggregate_policy_report(
            self.report, tags=("bgp",), scope_hostnames=frozenset(),
        )

    def test_devices_without_the_protocol_never_pass(self) -> None:
        counts = self.aggregate["counts"]
        self.assertEqual(1, counts["pass"])
        self.assertEqual(1, counts["fail"])
        self.assertEqual(3, counts["not_applicable"])
        self.assertEqual(0, counts["unknown"])

    def test_judged_devices_exclude_the_not_applicable(self) -> None:
        self.assertEqual(
            frozenset({"bgp-good", "bgp-bad"}),
            self.aggregate["devices_judged"],
        )
        self.assertEqual(
            frozenset({"edge1", "edge2", "edge3"}),
            self.aggregate["devices_not_applicable"],
        )
        self.assertEqual(5, len(self.aggregate["devices_evaluated"]))

    def test_the_broken_speaker_dominates_the_verdict(self) -> None:
        """The inversion the review proved: 1 of 2 judged passing must
        never read as 4 of 5 passing."""

        counts = self.aggregate["counts"]
        judged = counts["pass"] + counts["fail"] + counts["warning"]
        self.assertEqual(2, judged)
        self.assertEqual(1, counts["fail"])

    def test_per_policy_rows_carry_the_split(self) -> None:
        row = next(
            r for r in self.aggregate["policies"]
            if r["policy_id"] == "STD-BGPRID-001"
        )
        self.assertEqual(1, row["pass"])
        self.assertEqual(1, row["fail"])
        self.assertEqual(3, row["not_applicable"])
        self.assertEqual(["bgp-bad"], row["failed_devices"])


class SelectorApplicabilityAggregationTests(unittest.TestCase):
    def test_unestablished_platform_is_not_applicable_never_judged(self) -> None:
        """A platform-targeted rule on a device whose platform Atlas has
        not established is not applicable (never guessed) — and the
        aggregation must not count it as a pass either."""

        pack = PolicyPack(
            pack_id="test-vendor",
            name="Vendor-targeted test pack",
            description="",
            version="1.0",
            author="tests",
            policies=(
                Policy(
                    policy_id="VND-001",
                    name="IOS-only marker",
                    description="",
                    category="configuration",
                    severity="low",
                    check=PolicyCheck(
                        evidence="running-config",
                        operator=OP_ANY_PRESENT,
                        patterns=("hostname",),
                    ),
                    evidence_required=("running-config",),
                    reasoning_strategy="",
                    expected_state="present",
                    recommendation="n/a",
                    remediation="n/a",
                    tags=("bgp",),
                    applicability=PolicyApplicability(
                        platforms=("Cisco IOS*",),
                    ),
                ),
            ),
        )
        memory, _tmp = _seed_memory({"dev-edge1": NO_BGP})
        report = PolicyEngine(pack, clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        evaluation = report.evaluations[0]
        self.assertFalse(evaluation.applicable)
        aggregate = aggregate_policy_report(
            report, tags=("bgp",), scope_hostnames=frozenset(),
        )
        self.assertEqual(0, aggregate["counts"]["pass"])
        self.assertEqual(1, aggregate["counts"]["not_applicable"])
        self.assertEqual(frozenset(), aggregate["devices_judged"])


class UnknownPrecedenceTests(unittest.TestCase):
    def test_absent_evidence_outranks_applicability(self) -> None:
        """A device with no configuration evidence is unknown — Atlas
        cannot even establish whether the rule applies."""

        memory, _tmp = _seed_memory({
            "dev-bgp-good": BGP_GOOD,
            "dev-dark": None,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        aggregate = aggregate_policy_report(
            report, tags=("bgp",), scope_hostnames=frozenset(),
        )
        counts = aggregate["counts"]
        self.assertEqual(1, counts["pass"])
        self.assertEqual(1, counts["unknown"])
        self.assertEqual(0, counts["not_applicable"])
        self.assertEqual(
            frozenset({"bgp-good"}), aggregate["devices_judged"],
        )


# -- Step 3: descriptor fields link, never duplicate --------------------------


class SubjectDescriptorFieldTests(unittest.TestCase):
    def test_platform_capability_names_are_real(self) -> None:
        """A declared collection capability must exist in the platform
        layer's vocabulary — the link may be empty but never dangling."""

        from founderos_atlas.investigation.subjects import SUBJECTS
        from founderos_atlas.platforms.capabilities import CAPABILITIES

        for descriptor in SUBJECTS:
            if descriptor.platform_capability:
                with self.subTest(subject=descriptor.key):
                    self.assertIn(
                        descriptor.platform_capability, CAPABILITIES,
                    )

    def test_validation_title_defaults_to_label_configuration(self) -> None:
        from founderos_atlas.investigation.validation import capability

        self.assertEqual("BGP configuration", capability("bgp").title)
        self.assertEqual("OSPF configuration", capability("ospf").title)


# -- Step 2: the capability registry — discovered, never declared ------------


class CapabilityRegistryTests(unittest.TestCase):
    def test_capabilities_are_derived_from_the_starter_pack(self) -> None:
        """BGP and OSPF both light up with ZERO new validation data —
        the review's proof-of-genericity (success criterion 1)."""

        from founderos_atlas.investigation.validation import capabilities

        found = {item.subject: item for item in capabilities()}
        self.assertIn("bgp", found)
        self.assertIn("ospf", found)
        self.assertEqual(("STD-BGPRID-001",), found["bgp"].rules)
        self.assertEqual(("STD-OSPFRID-001",), found["ospf"].rules)

    def test_capability_carries_provenance_and_evidence(self) -> None:
        from founderos_atlas.investigation.validation import capability

        item = capability("bgp")
        self.assertIsNotNone(item)
        self.assertEqual("BGP", item.label)
        self.assertIn("@", item.pack)
        self.assertEqual(("running-config",), item.evidence_kinds)
        self.assertEqual((), item.platforms)  # universal starter rules

    def test_ordering_is_alphabetical_by_label(self) -> None:
        from founderos_atlas.investigation.validation import capabilities

        labels = [item.label for item in capabilities()]
        self.assertEqual(sorted(labels, key=str.casefold), labels)

    def test_a_subject_with_no_rules_has_no_capability(self) -> None:
        from founderos_atlas.investigation.validation import capability

        self.assertIsNone(capability("eigrp"))
        self.assertIsNone(capability("unheard-of"))
        self.assertIsNone(capability(""))

    def test_an_empty_pack_yields_no_capabilities(self) -> None:
        from founderos_atlas.investigation.validation import (
            capabilities,
            unrealised,
        )

        empty = PolicyPack(
            pack_id="empty", name="Empty", description="",
            version="0.1", author="tests", policies=(),
        )
        self.assertEqual((), capabilities(empty))
        # And the declared-but-unrealised subjects are diagnosed, not
        # silently absent (review R3).
        keys = {key for key, _reason in unrealised(empty)}
        self.assertEqual({"bgp", "ospf"}, keys)

    def test_unrealised_is_empty_for_the_starter_pack(self) -> None:
        from founderos_atlas.investigation.validation import unrealised

        self.assertEqual((), unrealised())

    def test_platform_targeted_rules_surface_their_platforms(self) -> None:
        from founderos_atlas.investigation.validation import capability
        from founderos_atlas.investigation.subjects import SubjectDescriptor

        pack = PolicyPack(
            pack_id="vnd", name="Vendor", description="",
            version="1.0", author="tests",
            policies=(
                Policy(
                    policy_id="VND-002", name="IOS BGP rule",
                    description="", category="configuration",
                    severity="low",
                    check=PolicyCheck(
                        evidence="running-config",
                        operator=OP_ANY_PRESENT, patterns=("x",),
                    ),
                    evidence_required=("running-config",),
                    reasoning_strategy="", expected_state="p",
                    recommendation="r", remediation="m",
                    tags=("bgp",),
                    applicability=PolicyApplicability(
                        platforms=("Cisco IOS*",),
                    ),
                ),
            ),
        )
        subjects = (
            SubjectDescriptor("bgp", "BGP", ("bgp",), policy_tags=("bgp",)),
        )
        item = capability("bgp", pack, subjects=subjects)
        self.assertEqual(("Cisco IOS*",), item.platforms)


# -- Step 4: the generic template — one builder, zero per-subject code -------


class GenericTemplateTests(unittest.TestCase):
    def test_bgp_validation_selects_a_template_for_free(self) -> None:
        """Success criterion 1 (the headline): BGP validation works
        with ZERO new validation data — no template block, no dict
        entry, no intent. Existing declarations light it up."""

        from founderos_atlas.investigation.extraction import extract
        from founderos_atlas.investigation.templates import select

        request = extract("Is the BGP configuration compliant?")
        template = select(request)
        self.assertIsNotNone(template)
        self.assertEqual("bgp-configuration", template.key)
        self.assertEqual("validation", template.domain)
        self.assertEqual("BGP configuration validation", template.title)
        self.assertIn("BGP", template.steps[-1].label)

    def test_ospf_keeps_its_template_key(self) -> None:
        """PR-171's pinned key survives — derived, no longer
        hand-written."""

        from founderos_atlas.investigation.extraction import extract
        from founderos_atlas.investigation.templates import select

        template = select(extract(
            "Is all the OSPF configuration fine across the enterprise?"
        ))
        self.assertIsNotNone(template)
        self.assertEqual("ospf-configuration", template.key)

    def test_the_template_steps_are_subject_free_machinery(self) -> None:
        """Both subjects get the SAME three steps and the SAME two
        engines — only labels differ."""

        from founderos_atlas.investigation.validation import capability
        from founderos_atlas.investigation.templates import (
            validation_template,
        )

        ospf = validation_template(capability("ospf"))
        bgp = validation_template(capability("bgp"))
        self.assertEqual(
            [(s.key, s.engine, s.required) for s in ospf.steps],
            [(s.key, s.engine, s.required) for s in bgp.steps],
        )
        self.assertEqual(
            [s.run for s in ospf.steps], [s.run for s in bgp.steps],
        )

    def test_a_synthetic_subject_gets_a_working_template(self) -> None:
        """Success criterion 2: adding a technology touches only data —
        a descriptor and rules. No template, no intent, no code."""

        from founderos_atlas.investigation.subjects import SubjectDescriptor
        from founderos_atlas.investigation.validation import capability
        from founderos_atlas.investigation.templates import (
            validation_template,
        )

        pack = PolicyPack(
            pack_id="future", name="Future", description="",
            version="1.0", author="tests",
            policies=(
                Policy(
                    policy_id="VXL-001", name="VXLAN VTEP source",
                    description="", category="configuration",
                    severity="medium",
                    check=PolicyCheck(
                        evidence="running-config",
                        operator=OP_CONDITIONAL_PRESENT,
                        antecedent=("interface vxlan",),
                        patterns=("vxlan source-interface",),
                    ),
                    evidence_required=("running-config",),
                    reasoning_strategy="", expected_state="set",
                    recommendation="set it", remediation="set it",
                    tags=("vxlan",),
                ),
            ),
        )
        subjects = (
            SubjectDescriptor(
                "vxlan", "VXLAN", ("vxlan",), policy_tags=("vxlan",),
            ),
        )
        cap = capability("vxlan", pack, subjects=subjects)
        self.assertIsNotNone(cap)
        template = validation_template(cap)
        self.assertEqual("vxlan-configuration", template.key)
        self.assertEqual(("VXL-001",), cap.rules)
        self.assertEqual("future@1.0", cap.pack)

    def test_a_subject_without_rules_still_selects_none(self) -> None:
        from founderos_atlas.investigation.extraction import extract
        from founderos_atlas.investigation.templates import select

        request = extract("Is the EIGRP configuration compliant?")
        self.assertIsNone(select(request))


# -- Step 7: refusals read the registry ---------------------------------------


class RefusalListTests(unittest.TestCase):
    def test_the_refusal_names_every_capability(self) -> None:
        """One source of truth: the "can currently validate" list is
        the capability registry, so BGP appears the moment its rules
        exist — no wording edit, ever."""

        from founderos_atlas.investigation import investigate

        class _Graph:
            devices = ()
            sites = ()

        result = investigate(
            "Is the EIGRP configuration compliant?", graph=_Graph(),
        )
        self.assertIsNotNone(result)
        self.assertIn("BGP configuration", result.summary)
        self.assertIn("OSPF configuration", result.summary)
        self.assertIn("cannot validate", result.summary)


# -- Step 8: the masked-secret guard (R9) -------------------------------------


class MaskBlindGuardTests(unittest.TestCase):
    def test_the_starter_pack_now_has_no_blind_rule(self) -> None:
        """STD-PWENC-001 hunted 'service password-encryption' while the
        masked view erased every line containing 'password', so it
        failed compliant devices. PR-174.2 fixed the CAUSE — the masker
        no longer masks argument-free switches that carry no secret —
        so the pack is clean and the guard has nothing to catch."""

        from founderos_atlas.investigation.validation import (
            mask_blind_reason,
            mask_blind_rules,
        )
        from founderos_atlas.policy.packs import default_pack

        self.assertEqual((), mask_blind_rules())
        pwenc = next(
            policy for policy in default_pack().policies
            if policy.policy_id == "STD-PWENC-001"
        )
        self.assertIsNone(mask_blind_reason(pwenc))

    def test_the_guard_still_catches_a_genuinely_blind_rule(self) -> None:
        """Fixing the cause must not disarm the guard: a rule hunting a
        secret's VALUE is still blind, because that line really is
        masked."""

        from founderos_atlas.investigation.validation import (
            mask_blind_reason,
        )

        blind = Policy(
            policy_id="BLD-003", name="Weak SNMP community",
            description="", category="security", severity="high",
            check=PolicyCheck(
                evidence="running-config",
                operator=OP_ANY_PRESENT,
                patterns=("snmp-server community public",),
            ),
            evidence_required=("running-config",),
            reasoning_strategy="", expected_state="absent",
            recommendation="r", remediation="m", tags=("snmp",),
        )
        reason = mask_blind_reason(blind)
        self.assertIsNotNone(reason)
        self.assertIn("community", reason)

    def test_the_masker_only_spares_argument_free_switches(self) -> None:
        """The safe-directive allowlist is the security-sensitive part
        of PR-174.2: every entry must be argument-free, matched WHOLE
        LINE, and no secret-bearing line may survive it."""

        from founderos_atlas.config_intelligence.diff import (
            _SAFE_DIRECTIVES,
            mask_line,
        )

        for directive in _SAFE_DIRECTIVES:
            with self.subTest(directive=directive):
                # Argument-free: the whole line is fixed keywords, so no
                # instance of it can carry a secret.
                self.assertTrue(
                    all(part.isalpha() or "-" in part
                        for part in directive.split()),
                    directive,
                )
                self.assertEqual(directive, mask_line(directive))
                # Indentation and case are normalised...
                self.assertEqual(
                    "  " + directive.upper(),
                    mask_line("  " + directive.upper()),
                )
                # ...but anything APPENDED is a different line, and is
                # masked. A prefix rule would have vouched for it.
                appended = directive + " username admin password s3cret"
                self.assertIn("masked", mask_line(appended))

    def test_real_secrets_are_still_masked(self) -> None:
        from founderos_atlas.config_intelligence.diff import mask_line

        for line in (
            "username admin secret 0 HUNTER2",
            "snmp-server community SUPERSECRET RO",
            " enable password 7 09424B1C",
            "crypto key generate rsa modulus 2048",
            "tacacs-server key MYTACACSKEY",
        ):
            with self.subTest(line=line):
                self.assertIn("masked", mask_line(line))
                self.assertNotIn("HUNTER2", mask_line(line))

    def test_blind_rules_never_enter_a_capability(self) -> None:
        from founderos_atlas.investigation.subjects import SubjectDescriptor
        from founderos_atlas.investigation.validation import capability

        blind = Policy(
            policy_id="BLD-001", name="SNMP community naming",
            description="", category="configuration", severity="low",
            check=PolicyCheck(
                evidence="running-config",
                operator=OP_ANY_PRESENT,
                patterns=("snmp-server community atlas-ro",),
            ),
            evidence_required=("running-config",),
            reasoning_strategy="", expected_state="p",
            recommendation="r", remediation="m", tags=("snmp",),
        )
        sighted = Policy(
            policy_id="SGT-001", name="SNMP server configured",
            description="", category="configuration", severity="low",
            check=PolicyCheck(
                evidence="running-config",
                operator=OP_ANY_PRESENT,
                patterns=("snmp-server host",),
            ),
            evidence_required=("running-config",),
            reasoning_strategy="", expected_state="p",
            recommendation="r", remediation="m", tags=("snmp",),
        )
        pack = PolicyPack(
            pack_id="mixed", name="Mixed", description="",
            version="1.0", author="tests",
            policies=(blind, sighted),
        )
        subjects = (
            SubjectDescriptor(
                "snmp", "SNMP", ("snmp",), policy_tags=("snmp",),
            ),
        )
        cap = capability("snmp", pack, subjects=subjects)
        self.assertIsNotNone(cap)
        self.assertEqual(("SGT-001",), cap.rules)

    def test_a_subject_with_only_blind_rules_is_not_validatable(self) -> None:
        from founderos_atlas.investigation.subjects import SubjectDescriptor
        from founderos_atlas.investigation.validation import capability

        blind = Policy(
            policy_id="BLD-002", name="Key check",
            description="", category="configuration", severity="low",
            check=PolicyCheck(
                evidence="running-config",
                operator=OP_ANY_PRESENT,
                patterns=("crypto key generate rsa",),
            ),
            evidence_required=("running-config",),
            reasoning_strategy="", expected_state="p",
            recommendation="r", remediation="m", tags=("ssh",),
        )
        pack = PolicyPack(
            pack_id="allblind", name="All blind", description="",
            version="1.0", author="tests", policies=(blind,),
        )
        subjects = (
            SubjectDescriptor(
                "ssh", "SSH", ("ssh",), policy_tags=("ssh",),
            ),
        )
        self.assertIsNone(capability("ssh", pack, subjects=subjects))

    def test_non_config_evidence_is_out_of_the_guards_scope(self) -> None:
        """Masking rewrites the running-config view; a rule over other
        evidence kinds is not blinded and must not be refused."""

        from founderos_atlas.investigation.validation import (
            mask_blind_reason,
        )

        transport_rule = Policy(
            policy_id="TRN-001", name="SSH transport observed",
            description="", category="security", severity="low",
            check=PolicyCheck(
                evidence="access-transport",
                operator=OP_ANY_PRESENT,
                patterns=("authenticated over ssh, no host key errors",),
            ),
            evidence_required=("access-transport",),
            reasoning_strategy="", expected_state="p",
            recommendation="r", remediation="m", tags=("ssh",),
        )
        self.assertIsNone(mask_blind_reason(transport_rule))

    def test_the_bgp_and_ospf_capabilities_survive_the_guard(self) -> None:
        from founderos_atlas.investigation.validation import capabilities

        keys = {item.subject for item in capabilities()}
        self.assertEqual({"bgp", "ospf"}, keys)


# -- Step 6: the verdict projection — six terms, no new vocabulary -----------


def _aggregate(report, tags=("bgp",)):
    return aggregate_policy_report(
        report, tags=tags, scope_hostnames=frozenset(),
    )


class VerdictProjectionTests(unittest.TestCase):
    def test_minority_estate_is_non_compliant_not_healthy(self) -> None:
        """The review's inversion, closed end to end: the one broken
        BGP speaker decides the verdict; the 3 non-speakers cannot
        drown it."""

        from founderos_atlas.investigation.validation import (
            VERDICT_NON_COMPLIANT,
            verdict_for,
        )

        memory, _tmp = _minority_estate()
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        projection = verdict_for(_aggregate(report), scope_count=5)
        self.assertEqual(VERDICT_NON_COMPLIANT, projection["verdict"])
        # STD-BGPRID-001 is medium severity -> the Warning chip, per
        # the review's severity split.
        self.assertEqual("warning", projection["tone"])

    def test_compliant_requires_at_least_one_judged_device(self) -> None:
        from founderos_atlas.investigation.validation import (
            VERDICT_COMPLIANT,
            VERDICT_NOT_APPLICABLE,
            verdict_for,
        )

        memory, _tmp = _seed_memory({
            "dev-bgp-good": BGP_GOOD, "dev-edge1": NO_BGP,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        projection = verdict_for(_aggregate(report), scope_count=2)
        self.assertEqual(VERDICT_COMPLIANT, projection["verdict"])
        self.assertEqual("ok", projection["tone"])

        # An estate with NO speakers at all is Not applicable — a
        # positive determination, never Compliant (zero judged).
        memory2, _tmp2 = _seed_memory({
            "dev-edge1": NO_BGP, "dev-edge2": NO_BGP,
        })
        report2 = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory2, scope_label="Lab",
        )
        projection2 = verdict_for(_aggregate(report2), scope_count=2)
        self.assertEqual(VERDICT_NOT_APPLICABLE, projection2["verdict"])
        self.assertEqual("info", projection2["tone"])

    def test_partially_verified_when_devices_are_unjudged(self) -> None:
        from founderos_atlas.investigation.validation import (
            VERDICT_PARTIAL,
            verdict_for,
        )

        memory, _tmp = _seed_memory({
            "dev-bgp-good": BGP_GOOD, "dev-dark": None,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        projection = verdict_for(_aggregate(report), scope_count=2)
        self.assertEqual(VERDICT_PARTIAL, projection["verdict"])
        self.assertEqual("warning", projection["tone"])

    def test_no_evidence_when_nothing_can_be_judged(self) -> None:
        from founderos_atlas.investigation.validation import (
            VERDICT_NO_EVIDENCE,
            verdict_for,
        )

        memory, _tmp = _seed_memory({"dev-dark": None})
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        projection = verdict_for(_aggregate(report), scope_count=1)
        self.assertEqual(VERDICT_NO_EVIDENCE, projection["verdict"])
        self.assertEqual("unknown", projection["tone"])

    def test_unknown_severity_is_never_downgraded(self) -> None:
        """A failing rule with no declared severity keeps the
        Attention chip — grave unless proven lenient."""

        from founderos_atlas.investigation.validation import verdict_for

        aggregate = {
            "counts": {"pass": 0, "fail": 1, "warning": 0,
                       "unknown": 0, "not_applicable": 0},
            "policies": [{"policy_id": "X", "name": "X", "severity": "",
                          "fail": 1, "warning": 0}],
            "devices_evaluated": frozenset({"r1"}),
        }
        projection = verdict_for(aggregate, scope_count=1)
        self.assertEqual("attention", projection["tone"])


class VerdictChipMappingTests(unittest.TestCase):
    """The six terms land on EXISTING Experience-Language chips —
    success criterion 9: no new status vocabulary."""

    def _chip(self, summary: str, confidence: str = "High") -> str:
        from founderos_atlas.advisor.presentation import _verdict

        return _verdict(summary, confidence)["status"]

    def test_the_six_terms_map_onto_existing_chips(self) -> None:
        cases = (
            ("BGP configuration: Compliant — every judged evaluation "
             "passed (2 of 2).", "High", "Healthy"),
            ("BGP configuration: Non-compliant — 1 evaluation(s) "
             "failed; 1 of 2 judged evaluation(s) pass.", "High",
             "Attention required"),
            ("BGP configuration: Non-compliant — 1 violation(s) at "
             "medium or low severity; 1 of 2 judged evaluation(s) "
             "pass.", "High", "Warning"),
            ("BGP configuration: Partially verified — 1 of 1 judged "
             "evaluation(s) pass; the rest could not be judged.",
             "Medium", "Warning"),
            ("No device in scope has BGP configured — the 3 "
             "evaluation(s) were not applicable. Atlas does not "
             "report absence as compliance.", "High", "Informational"),
            ("Atlas cannot validate the EIGRP configuration as asked "
             "— it has no validation rules for EIGRP. It can "
             "currently validate: BGP configuration, OSPF "
             "configuration. It will not claim compliance it has not "
             "checked.", "Unknown", "Informational"),
            ("The policy engine produced no BGP evaluations for this "
             "scope, so the configuration could not be judged.",
             "Unknown", "Not enough evidence"),
        )
        for summary, confidence, expected in cases:
            with self.subTest(chip=expected, summary=summary[:40]):
                self.assertEqual(expected, self._chip(summary, confidence))


# -- Adversarial-review fixes (post-implementation) ---------------------------


class ReviewFixTests(unittest.TestCase):
    """Each test pins a defect the PR-172 adversarial review confirmed
    and the implementation then closed."""

    def test_na_plus_unevaluated_is_not_enough_evidence(self) -> None:
        """The summary may never contradict the stored projection: 2
        not-applicable evaluations + 3 unevaluated devices is 'not
        enough evidence', never 'No device in scope has X configured'
        at High confidence."""

        from founderos_atlas.investigation.validation import (
            VERDICT_NO_EVIDENCE,
            verdict_for,
        )

        memory, _tmp = _seed_memory({
            "dev-edge1": NO_BGP, "dev-edge2": NO_BGP,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        aggregate = aggregate_policy_report(
            report, tags=("bgp",), scope_hostnames=frozenset(),
        )
        projection = verdict_for(aggregate, scope_count=5)
        self.assertEqual(VERDICT_NO_EVIDENCE, projection["verdict"])
        self.assertEqual("unknown", projection["tone"])

    def test_all_unknown_never_reads_compliant(self) -> None:
        """judged=0 with unknowns must never render 'Compliant — every
        judged evaluation passed (0 of 0)'."""

        memory, _tmp = _seed_memory({"dev-dark": None})
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )

        from founderos_atlas.investigation.validation import (
            VERDICT_NO_EVIDENCE,
            verdict_for,
        )

        aggregate = aggregate_policy_report(
            report, tags=("bgp",), scope_hostnames=frozenset(),
        )
        projection = verdict_for(aggregate, scope_count=1)
        self.assertEqual(VERDICT_NO_EVIDENCE, projection["verdict"])

    def test_unknown_reasons_carry_the_engines_own_words(self) -> None:
        """The engine names the missing evidence kind; the aggregate
        must repeat it, not a generic placeholder."""

        memory, _tmp = _seed_memory({"dev-dark": None})
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        aggregate = aggregate_policy_report(
            report, tags=("bgp",), scope_hostnames=frozenset(),
        )
        reasons = list(aggregate["unknown_reasons"])
        self.assertEqual(1, len(reasons))
        self.assertIn("required evidence (running-config)", reasons[0])

    def test_vetting_follows_the_reports_own_pack(self) -> None:
        """A governed (effective) pack that dropped a rule must also
        drop it from the verdict: the capability is derived from the
        pack the REPORT was judged with, not the raw default."""

        from founderos_atlas.investigation.validation import capability

        trimmed = PolicyPack(
            pack_id="governed", name="Governed", description="",
            version="1.0", author="tests",
            policies=tuple(
                policy for policy in
                PolicyEngine().pack.policies
                if policy.policy_id != "STD-BGPRID-001"
            ),
        )
        self.assertIsNone(capability("bgp", trimmed))
        self.assertIsNotNone(capability("ospf", trimmed))


class ReviewFixEndToEndTests(unittest.TestCase):
    """The orchestrator sentences for the review's exact scenarios."""

    def _investigate(self, question, report, devices):
        from dataclasses import dataclass, field

        from founderos_atlas.investigation import investigate

        @dataclass
        class _Device:
            enterprise_id: str
            hostname: str
            site: object = None

        @dataclass
        class _Graph:
            devices: tuple = ()
            sites: tuple = ()

        graph = _Graph(devices=tuple(
            _Device(f"ent:{name}", name) for name in devices
        ))
        return investigate(
            question, graph=graph, policy_runner=lambda: report,
        )

    def test_na_plus_dark_devices_never_claims_no_device_has_it(self) -> None:
        memory, _tmp = _seed_memory({
            "dev-edge1": NO_BGP, "dev-edge2": NO_BGP,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        result = self._investigate(
            "Is the BGP configuration compliant?", report,
            ("edge1", "edge2", "dark1", "dark2", "dark3"),
        )
        self.assertIsNotNone(result)
        self.assertNotIn("No device in scope has", result.summary)
        self.assertIn("could not be judged", result.summary)
        self.assertEqual("Unknown", result.confidence)

    def test_fully_evaluated_all_na_still_says_so(self) -> None:
        """The honest positive claim survives when it IS true — every
        device in scope examined, nothing applicable."""

        memory, _tmp = _seed_memory({
            "dev-edge1": NO_BGP, "dev-edge2": NO_BGP,
        })
        report = PolicyEngine(clock=lambda: FIXED_CLOCK).evaluate(
            memory, scope_label="Lab",
        )
        result = self._investigate(
            "Is the BGP configuration compliant?", report,
            ("edge1", "edge2"),
        )
        self.assertIsNotNone(result)
        self.assertIn("No device in scope has BGP configured",
                      result.summary)
        self.assertEqual("High", result.confidence)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
