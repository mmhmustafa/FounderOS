"""PR-171 — Question Understanding.

The claims under test, in the corrected review's own order:

* Direct phrase matching is word-anchored — "breach" no longer selects
  the connectivity engine, "exchanges" no longer selects changes.
* Dispatch reads (engine, objective), so a resolved intent influences
  execution instead of surviving as display decoration — while every
  pre-existing intent keeps its exact behaviour through the default.
* The question dimensions are extracted deterministically: subject,
  objective (validate gated on a subject), and a POSITIVE scope.
* Selection is specific-first, None stays a legitimate outcome, and
  the PR-167 estate-wide contract holds.
* Validation is honest end-to-end: no policies means a refusal, never
  a pass; unjudged devices stay unknown with a reason.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from founderos_atlas.investigation.extraction import (
    OBJECTIVE_ASSESS,
    OBJECTIVE_COMPARE,
    OBJECTIVE_EXPLAIN,
    OBJECTIVE_FORECAST,
    OBJECTIVE_LOCATE,
    OBJECTIVE_VALIDATE,
    SCOPE_ENTERPRISE,
    SCOPE_SITES,
    extract,
)
from founderos_atlas.investigation.templates import select
from founderos_atlas.oir.detection import detect


# -- Step 0: word-anchored direct routing -----------------------------------

class PhraseAnchoringTests(unittest.TestCase):
    """A phrase can no longer fire from the middle of a longer word."""

    def test_a_security_breach_is_not_a_connectivity_question(self) -> None:
        """CONFIRMED misroute: "breach" contains "reach", so this
        routed to Connectivity Validation on the path engine at HIGH
        confidence, with no escalation flag to warn anyone."""

        route = detect("Was there a security breach last night?")
        self.assertNotEqual(route.engine, "path")
        self.assertNotEqual(route.intent.key, "connectivity-validation")

    def test_an_exchange_inventory_is_not_a_change_question(self) -> None:
        """CONFIRMED misroute: "exchanges" contains "changes"."""

        route = detect("Show me the inventory of exchanges")
        self.assertNotEqual(route.engine, "changes")
        self.assertNotEqual(route.intent.key, "change-analysis")

    def test_correct_routes_are_preserved(self) -> None:
        for question, engine in (
            ("Is the network healthy?", "health"),
            ("What changed?", "changes"),
            ("Can core1 reach core2?", "path"),
        ):
            with self.subTest(question=question):
                self.assertEqual(detect(question).engine, engine)

    def test_prefix_style_phrases_still_fire(self) -> None:
        """Registered phrases like "how is " end mid-word on purpose —
        word-START anchoring must not break them."""

        route = detect("How is the enterprise doing?")
        self.assertEqual(route.engine, "health")

    def test_a_too_short_phrase_is_refused_at_freeze(self) -> None:
        from founderos_atlas.oir.registry import IntentDefinition
        from founderos_atlas.oir.validation import validate_definitions

        problems = validate_definitions([IntentDefinition(
            name="X", key="x", description="d", engine="health",
            domain="d", confidence_rule="r",
            routing_phrases=("ok",), routing_priority=999,
        )])
        self.assertTrue(any("shorter than" in item for item in problems))


# -- Step 0b: (engine, objective) dispatch -----------------------------------

class ObjectiveDispatchTests(unittest.TestCase):

    def test_every_preexisting_intent_takes_the_default_objective(
        self,
    ) -> None:
        """Success criterion 10: (engine, objective) dispatch must
        reproduce today's behaviour exactly, which requires every
        pre-PR-171 intent to declare "assess"."""

        from founderos_atlas.oir.service import default_router

        for definition in default_router().registry.definitions():
            if definition.key == "configuration-validation":
                continue
            with self.subTest(intent=definition.key):
                self.assertEqual(definition.objective, "assess")

    def test_no_assess_key_exists_in_the_objective_table(self) -> None:
        """The objective table must be sparse: an (engine, "assess")
        entry would shadow an engine handler and change a route the
        contract says is unchanged."""

        from founderos_atlas.advisor.engine import _OBJECTIVE_HANDLERS

        for engine, objective in _OBJECTIVE_HANDLERS:
            self.assertNotEqual(objective, "assess")

    def test_the_ospf_question_routes_to_the_validation_intent(
        self,
    ) -> None:
        route = detect(
            "Is all the OSPF configuration fine across the enterprise?"
        )
        self.assertEqual(route.intent.key, "configuration-validation")
        self.assertEqual(route.intent.objective, "validate")

    def test_an_unknown_objective_is_refused_at_freeze(self) -> None:
        from founderos_atlas.oir.registry import IntentDefinition
        from founderos_atlas.oir.validation import validate_definitions

        problems = validate_definitions([IntentDefinition(
            name="X", key="x", description="d", engine="health",
            domain="d", confidence_rule="r", objective="guess",
        )])
        self.assertTrue(any("unknown objective" in item
                            for item in problems))


# -- Step 2: the objective dimension -----------------------------------------

class ObjectiveExtractionTests(unittest.TestCase):

    def test_each_objective_from_its_own_words(self) -> None:
        for question, expected in (
            ("Is all the OSPF configuration fine?", OBJECTIVE_VALIDATE),
            ("Why did OSPF drop at Chennai?", OBJECTIVE_EXPLAIN),
            ("What changed in the network?", OBJECTIVE_COMPARE),
            ("What is the risk of this change?", OBJECTIVE_FORECAST),
            ("Find core1", OBJECTIVE_LOCATE),
            ("Is OSPF healthy?", OBJECTIVE_ASSESS),
            ("Tell me about the network", OBJECTIVE_ASSESS),  # default
        ):
            with self.subTest(question=question):
                self.assertEqual(extract(question).objective, expected)

    def test_validate_requires_a_subject(self) -> None:
        """R2: "is the network fine?" must stay an assessment — without
        a subject there is nothing whose configuration could be judged."""

        request = extract("Is the network configuration fine?")
        # "network" is not a subject; "configuration" is — so this one
        # IS a validation, of the configuration domain subject.
        self.assertEqual(request.objective, OBJECTIVE_VALIDATE)

        bare = extract("Is everything fine?")
        self.assertEqual(bare.objective, OBJECTIVE_ASSESS)
        self.assertEqual(bare.subject, "")

    def test_a_lookup_of_a_configuration_is_not_a_validation(self) -> None:
        """"Configuration" alone is a subject, not a judgement. Sending
        "show me the X configuration" to the compliance engine would
        answer a question nobody asked."""

        request = extract("Show me the OSPF configuration")
        self.assertEqual(request.objective, OBJECTIVE_LOCATE)
        self.assertEqual(request.subject, "ospf")

    def test_every_dimension_states_its_basis(self) -> None:
        request = extract(
            "Is all the OSPF configuration fine across the enterprise?"
        )
        text = " ".join(request.basis)
        self.assertIn("protocol recognised", text)
        self.assertIn("configuration terminology detected", text)
        self.assertIn("scope enterprise", text)


# -- Step 3: positive scope ---------------------------------------------------

class PositiveScopeTests(unittest.TestCase):

    def test_enterprise_phrasing_is_a_positive_scope(self) -> None:
        for phrase in ("across the enterprise", "everywhere",
                       "all sites", "fleet-wide"):
            with self.subTest(phrase=phrase):
                request = extract(f"Is OSPF configured correctly {phrase}?")
                self.assertEqual(request.scope, SCOPE_ENTERPRISE)

    def test_a_validation_naming_no_place_is_enterprise_scoped(self) -> None:
        request = extract("Is the OSPF configuration compliant?")
        self.assertEqual(request.scope, SCOPE_ENTERPRISE)
        self.assertTrue(any("estate-wide" in item for item in request.basis))

    def test_a_named_site_is_a_sites_scope(self) -> None:
        request = extract("Is OSPF healthy at chennai?",
                          known_sites=("chennai",))
        self.assertEqual(request.scope, SCOPE_SITES)

    def test_subject_and_scope_are_orthogonal(self) -> None:
        request = extract(
            "Is all the OSPF configuration fine across the enterprise?"
        )
        self.assertTrue(request.has_subject)
        self.assertTrue(request.has_scope)
        # ...and the PR-167 predicate keeps its original meaning:
        # nothing PLACED was named, so named_anything stays False.
        self.assertFalse(request.named_anything)


# -- Step 4: selection ---------------------------------------------------------

class SelectionTests(unittest.TestCase):

    def test_the_example_question_selects_the_validation_template(
        self,
    ) -> None:
        request = extract(
            "Is all the OSPF configuration fine across the enterprise?"
        )
        template = select(request)
        self.assertIsNotNone(template)
        self.assertEqual(template.key, "ospf-configuration")

    def test_the_assess_ladder_is_unchanged(self) -> None:
        """PR-173 (R8, reviewed edit): a judgement-phrased assessment
        of a state-capable subject — "Is OSPF healthy at chennai?" —
        now upgrades from the adjacency LISTING to a judged state
        verdict (ospf-state). Every other rung is byte-for-byte
        PR-167: endpoints keep the peering investigation, and
        "show me" extracts objective=locate, so listings stay
        listings."""

        for question, sites, expected in (
            ("How is BGP between mumbai and hyderabad?",
             ("mumbai", "hyderabad"), "bgp-between"),
            ("Is OSPF healthy at chennai?", ("chennai",), "ospf-state"),
            ("Show me BGP for ahmedabad", ("ahmedabad",), "bgp-scope"),
            ("Tell me about chennai", ("chennai",), "site-scope"),
        ):
            with self.subTest(question=question):
                template = select(extract(question, known_sites=sites))
                self.assertEqual(template.key, expected)

    def test_none_remains_a_legitimate_outcome(self) -> None:
        """The PR-167 estate-wide contract, re-asserted at the seam it
        depends on: a question naming nothing selects no template."""

        for question in ("Is the network healthy?",
                         "Explain enterprise health",
                         "Tell me a story"):
            with self.subTest(question=question):
                self.assertIsNone(select(extract(question)))

    def test_a_validatable_question_with_no_capability_selects_none(
        self,
    ) -> None:
        """EIGRP declares no policy tags, so no capability exists
        (PR-172) — selection returns None and the orchestrator refuses
        honestly instead of running an adjacency investigation."""

        request = extract("Is the EIGRP configuration compliant?")
        self.assertEqual(request.objective, OBJECTIVE_VALIDATE)
        self.assertIsNone(select(request))


# -- Step 5: honest validation end-to-end --------------------------------------

@dataclass
class _Device:
    enterprise_id: str
    hostname: str
    site: object = None


@dataclass
class _Graph:
    devices: tuple = ()
    sites: tuple = ()
    interfaces: dict = field(default_factory=dict)
    links: tuple = ()
    attributes: dict = field(default_factory=dict)

    def device_by_id(self, device_id):
        for device in self.devices:
            if device.enterprise_id == device_id:
                return device
        return None


@dataclass
class _StubPolicy:
    policy_id: str
    name: str
    tags: tuple


@dataclass
class _StubResult:
    summary: str = ""


@dataclass
class _StubEvaluation:
    policy: _StubPolicy
    hostname: str
    device_id: str
    status: str
    result: _StubResult = field(default_factory=_StubResult)


@dataclass
class _StubReport:
    evaluations: tuple


def _estate() -> _Graph:
    return _Graph(devices=(
        _Device("ent:r1", "r1"), _Device("ent:r2", "r2"),
        _Device("ent:r3", "r3"),
    ))


OSPF_POLICY = _StubPolicy("STD-OSPFRID-001", "OSPF Router ID Present",
                          ("routing", "ospf", "stability"))


class ValidationInvestigationTests(unittest.TestCase):

    def investigate(self, question, report):
        from founderos_atlas.investigation import investigate

        return investigate(
            question, graph=_estate(),
            policy_runner=(lambda: report) if report is not None else None,
        )

    def test_the_example_question_end_to_end(self) -> None:
        report = _StubReport(evaluations=(
            _StubEvaluation(OSPF_POLICY, "r1", "ent:r1", "pass"),
            _StubEvaluation(OSPF_POLICY, "r2", "ent:r2", "fail"),
        ))
        result = self.investigate(
            "Is all the OSPF configuration fine across the enterprise?",
            report,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.plan.template, "ospf-configuration")
        self.assertIn("1 evaluation(s) failed", result.summary)
        self.assertIn("1 of 2 judged", result.summary)
        # r3 was never judged: unknown WITH the reason, never compliant.
        self.assertTrue(any("no configuration evidence" in gap
                            for gap in result.gaps))
        self.assertIn("1 device(s) in scope have no configuration "
                      "evidence", result.summary)
        # Findings deep-link to the policy page.
        self.assertTrue(any(item.href == "/policy"
                            for item in result.findings))
        # The estate summary's phrasing never appears.
        self.assertNotIn("managed device(s)", result.summary)

    def test_all_passing_reads_as_a_clean_verdict(self) -> None:
        report = _StubReport(evaluations=tuple(
            _StubEvaluation(OSPF_POLICY, name, f"ent:{name}", "pass")
            for name in ("r1", "r2", "r3")
        ))
        result = self.investigate(
            "Is the OSPF configuration compliant?", report,
        )
        self.assertIn("every judged evaluation passed", result.summary)
        self.assertEqual(result.confidence, "High")
        # The negated-form discipline: a clean verdict must not trip
        # the presentation layer's attention markers.
        self.assertNotIn("failed", result.summary)

    def test_unknown_dispositions_stay_unknown_with_a_reason(self) -> None:
        report = _StubReport(evaluations=(
            _StubEvaluation(OSPF_POLICY, "r1", "ent:r1", "pass"),
            _StubEvaluation(OSPF_POLICY, "r2", "ent:r2", "unknown",
                            _StubResult("no running-config was collected")),
            _StubEvaluation(OSPF_POLICY, "r3", "ent:r3", "unknown",
                            _StubResult("no running-config was collected")),
        ))
        result = self.investigate(
            "Is the OSPF configuration correct?", report,
        )
        self.assertIn("2 evaluation(s) could not be judged", result.summary)
        self.assertTrue(any("no running-config was collected" in gap
                            for gap in result.gaps))
        self.assertEqual(result.confidence, "Medium")

    def test_no_matching_policies_refuses_rather_than_passing(self) -> None:
        """Success criterion 4 — the highest-ranked risk (R3). An empty
        rule set must never read as compliance."""

        report = _StubReport(evaluations=(
            _StubEvaluation(
                _StubPolicy("STD-NTP-001", "NTP Configured", ("time",)),
                "r1", "ent:r1", "pass",
            ),
        ))
        result = self.investigate(
            "Is the OSPF configuration compliant?", report,
        )
        self.assertIn("no configuration policies for OSPF", result.summary)
        self.assertEqual(result.confidence, "Unknown")
        self.assertNotIn("passed", result.summary)

    def test_an_unvalidatable_subject_refuses_honestly(self) -> None:
        """Success criterion 3: name what Atlas CAN do — never the
        estate summary, never an adjacency report in validation's
        clothing. EIGRP has no capability (PR-172: BGP now does)."""

        result = self.investigate(
            "Is the EIGRP configuration compliant?", None,
        )
        self.assertIsNotNone(result)
        self.assertIn("cannot validate the EIGRP configuration",
                      result.summary)
        self.assertIn("OSPF configuration", result.summary)
        self.assertEqual(result.confidence, "Unknown")
        self.assertNotIn("managed device(s)", result.summary)

    def test_no_runner_means_could_not_judge_never_compliant(self) -> None:
        result = self.investigate(
            "Is the OSPF configuration compliant?", None,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("passed", result.summary)
        self.assertTrue(
            any("could not be judged" in gap or "not available" in gap
                for gap in result.gaps)
        )


class AggregationTests(unittest.TestCase):
    """The shared aggregation helper both answer paths read."""

    def test_scope_filtering_judges_only_the_named_devices(self) -> None:
        from founderos_atlas.investigation.engines import (
            aggregate_policy_report,
        )

        report = _StubReport(evaluations=(
            _StubEvaluation(OSPF_POLICY, "r1", "ent:r1", "fail"),
            _StubEvaluation(OSPF_POLICY, "r2", "ent:r2", "pass"),
        ))
        aggregate = aggregate_policy_report(
            report, tags=("ospf",), scope_hostnames=frozenset({"r2"}),
        )
        self.assertEqual(aggregate["counts"]["fail"], 0)
        self.assertEqual(aggregate["counts"]["pass"], 1)

    def test_a_malformed_report_never_raises(self) -> None:
        from founderos_atlas.investigation.engines import (
            aggregate_policy_report,
        )

        aggregate = aggregate_policy_report(
            object(), tags=("ospf",), scope_hostnames=frozenset(),
        )
        self.assertEqual(aggregate["evaluated"], 0)
        self.assertEqual(aggregate["policies"], [])


# -- presentation: the verdict relabels the policy engine's determination ----

class ValidationPresentationTests(unittest.TestCase):

    def test_an_all_pass_validation_reads_healthy(self) -> None:
        """"Every judged evaluation passed" is the policy engine's own
        100%-pass determination — the verdict relabels it, computing
        nothing new."""

        from founderos_atlas.advisor.presentation import present_answer

        shown = present_answer({
            "summary": "OSPF configuration: every judged evaluation "
                       "passed (85 of 85).",
            "confidence": "High",
        })
        self.assertEqual(shown["verdict"]["status"], "Healthy")

    def test_a_failing_validation_demands_attention(self) -> None:
        from founderos_atlas.advisor.presentation import present_answer

        shown = present_answer({
            "summary": "OSPF configuration: 4 evaluation(s) failed; "
                       "62 of 66 judged evaluation(s) pass.",
            "confidence": "High",
        })
        self.assertEqual(shown["verdict"]["status"], "Attention required")

    def test_a_partial_pass_stays_informational(self) -> None:
        """"5 of 9 pass" with unknowns is not the all-pass sentence, so
        the verdict must NOT read Healthy from it."""

        from founderos_atlas.advisor.presentation import present_answer

        shown = present_answer({
            "summary": "OSPF configuration: 5 of 9 judged evaluation(s) "
                       "pass. 4 evaluation(s) could not be judged and "
                       "remain unknown.",
            "confidence": "Medium",
        })
        self.assertEqual(shown["verdict"]["status"], "Informational")

    def test_the_policy_engine_earns_investigated_chips(self) -> None:
        from founderos_atlas.advisor.presentation import present_answer

        shown = present_answer({
            "summary": "OSPF configuration: every judged evaluation "
                       "passed (85 of 85).",
            "confidence": "High",
            "investigation": {
                "request": {"protocol": "ospf"},
                "entities": {},
                "plan": {"title": "OSPF configuration validation",
                         "steps": []},
                "findings": [],
                "engines_used": ["graph", "policy"],
                "duration_ms": 12,
            },
        })
        self.assertIn("OSPF", shown["investigated"])
        self.assertIn("Policy compliance", shown["investigated"])


# -- Step 6: the understanding block -------------------------------------------

class UnderstandingBlockTests(unittest.TestCase):

    def test_the_schema_gained_understanding_additively(self) -> None:
        from founderos_atlas.advisor.models import (
            ADVISOR_SCHEMA_VERSION,
            AdvisorResponse,
        )

        self.assertEqual(ADVISOR_SCHEMA_VERSION, "1.3.0")
        payload = AdvisorResponse(
            question="q", intent="health", summary="s", evidence=(),
            confidence="High", confidence_basis="b",
            next_action_label="l", next_action_href="/",
        ).to_dict()
        # Every earlier key survives; understanding is new and optional.
        for key in ("question", "intent", "summary", "evidence",
                    "confidence", "operational_intent", "investigation"):
            self.assertIn(key, payload)
        self.assertIn("understanding", payload)
        self.assertIsNone(payload["understanding"])


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
