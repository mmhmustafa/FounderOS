"""PR-173 — Operational State Validation acceptance tests.

The defining discipline under test: **state is perishable**. A
three-day-old "Established" is not evidence that BGP is up now, so a
stale or undated observation set can never support a health verdict —
and every verdict that IS given states its observation age.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from founderos_atlas.investigation.state import (
    DEFAULT_HORIZON_MINUTES,
    FRESHNESS_AGEING,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    STATE_KIND_BGP_SESSIONS,
    STATE_KIND_INTERFACE_STATUS,
    STATE_KIND_OSPF_ADJACENCIES,
    observation_age_sentence,
    observations_for,
    state_freshness,
)


NOW = "2026-08-03T12:00:00+00:00"


@dataclass(frozen=True)
class _Contribution:
    profile_name: str
    observed_at: str | None


@dataclass
class _Interface:
    name: str
    status: str
    protocol_status: str
    observed_by: tuple = ()


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
    contributions: tuple = ()
    attributes: dict = field(default_factory=dict)


def _graph_with_bgp(sessions, *, contribution_at=NOW, observed_by="Lab"):
    rows = []
    for peer, state in sessions:
        rows.append({
            "peer_address": peer, "remote_as": "65001",
            "local_as": "65000", "state": state, "vrf": "default",
            "address_family": "ipv4-unicast",
            "source_command": "show bgp summary",
            "observed_by": observed_by,
        })
    return _Graph(
        devices=(_Device("ent:r1", "r1"),),
        contributions=(_Contribution("Lab", contribution_at),),
        attributes={"device_metadata": {"ent:r1": {
            "routing_evidence": {"bgp_sessions": rows,
                                 "ospf_adjacencies": []},
        }}},
    )


# -- S1: the provider ---------------------------------------------------------


class StateProviderTests(unittest.TestCase):
    def test_observations_are_dated_by_the_contribution_join(self) -> None:
        graph = _graph_with_bgp(
            [("10.0.0.2", "established")],
            contribution_at="2026-08-03T11:30:00+00:00",
        )
        result = observations_for(graph, "ent:r1", STATE_KIND_BGP_SESSIONS)
        self.assertEqual(1, len(result.items))
        self.assertEqual("2026-08-03T11:30:00+00:00", result.observed_at)
        self.assertEqual(("show bgp summary",), result.source_commands)

    def test_an_items_own_stamp_wins_over_the_contribution(self) -> None:
        graph = _graph_with_bgp([("10.0.0.2", "established")])
        row = graph.attributes["device_metadata"]["ent:r1"][
            "routing_evidence"]["bgp_sessions"][0]
        row["observed_at"] = "2026-08-03T11:59:00+00:00"
        result = observations_for(graph, "ent:r1", STATE_KIND_BGP_SESSIONS)
        self.assertEqual("2026-08-03T11:59:00+00:00", result.observed_at)

    def test_a_set_with_any_undatable_member_is_undated(self) -> None:
        """The set is only as current as its stalest member — one
        unattributable observation undates the whole set."""

        graph = _graph_with_bgp([
            ("10.0.0.2", "established"), ("10.0.0.3", "idle"),
        ])
        rows = graph.attributes["device_metadata"]["ent:r1"][
            "routing_evidence"]["bgp_sessions"]
        rows[1]["observed_by"] = "unknown-profile"
        result = observations_for(graph, "ent:r1", STATE_KIND_BGP_SESSIONS)
        self.assertIsNone(result.observed_at)

    def test_identities_are_stable_and_exclude_state(self) -> None:
        up = _graph_with_bgp([("10.0.0.2", "established")])
        down = _graph_with_bgp([("10.0.0.2", "idle")])
        first = observations_for(up, "ent:r1", STATE_KIND_BGP_SESSIONS)
        second = observations_for(down, "ent:r1", STATE_KIND_BGP_SESSIONS)
        self.assertEqual(first.identities, second.identities)
        self.assertEqual(
            ("ent:r1|bgp|default|ipv4-unicast|10.0.0.2",),
            first.identities,
        )

    def test_interfaces_come_from_the_graph(self) -> None:
        graph = _Graph(
            devices=(_Device("ent:r1", "r1"),),
            interfaces={"ent:r1": (
                _Interface("eth1", "up", "up", ("Lab",)),
                _Interface("eth2", "down", "down", ("Lab",)),
            )},
            contributions=(_Contribution("Lab", NOW),),
        )
        result = observations_for(
            graph, "ent:r1", STATE_KIND_INTERFACE_STATUS,
        )
        self.assertEqual(2, len(result.items))
        self.assertEqual(NOW, result.observed_at)
        self.assertEqual(
            ("ent:r1|interface|eth1", "ent:r1|interface|eth2"),
            result.identities,
        )

    def test_no_observations_is_an_empty_set_never_health(self) -> None:
        graph = _Graph(devices=(_Device("ent:r1", "r1"),))
        result = observations_for(graph, "ent:r1", STATE_KIND_BGP_SESSIONS)
        self.assertEqual((), result.items)
        self.assertIsNone(result.observed_at)

    def test_the_provider_never_reads_config_memory(self) -> None:
        """Configured intent is not operational state (review §1.4)."""

        import founderos_atlas.investigation.state as state_module

        source = open(state_module.__file__, encoding="utf-8").read()
        self.assertNotIn("config_memory", source.replace(
            "``config_memory``", ""
        ))


# -- S2: the freshness gate ---------------------------------------------------


class FreshnessGateTests(unittest.TestCase):
    def test_fresh_within_the_horizon(self) -> None:
        self.assertEqual(FRESHNESS_FRESH, state_freshness(
            "2026-08-03T11:30:00+00:00", now=NOW, horizon_minutes=60,
        ))

    def test_ageing_between_one_and_four_horizons(self) -> None:
        self.assertEqual(FRESHNESS_AGEING, state_freshness(
            "2026-08-03T09:00:00+00:00", now=NOW, horizon_minutes=60,
        ))

    def test_stale_beyond_four_horizons(self) -> None:
        self.assertEqual(FRESHNESS_STALE, state_freshness(
            "2026-08-03T07:59:00+00:00", now=NOW, horizon_minutes=60,
        ))

    def test_undated_is_stale_never_assumed_recent(self) -> None:
        self.assertEqual(
            FRESHNESS_STALE, state_freshness(None, now=NOW),
        )
        self.assertEqual(
            FRESHNESS_STALE, state_freshness("not-a-date", now=NOW),
        )

    def test_future_dated_is_stale(self) -> None:
        self.assertEqual(FRESHNESS_STALE, state_freshness(
            "2026-08-03T13:00:00+00:00", now=NOW,
        ))

    def test_the_default_horizon_is_an_hour(self) -> None:
        self.assertEqual(60, DEFAULT_HORIZON_MINUTES)

    def test_age_is_spoken_in_operator_words(self) -> None:
        self.assertEqual(
            "observed 30 minute(s) ago",
            observation_age_sentence(
                "2026-08-03T11:30:00+00:00", now=NOW,
            ),
        )
        self.assertEqual(
            "observed 3 hour(s) ago",
            observation_age_sentence(
                "2026-08-03T09:00:00+00:00", now=NOW,
            ),
        )
        self.assertEqual(
            "observed 3 day(s) ago",
            observation_age_sentence(
                "2026-07-31T12:00:00+00:00", now=NOW,
            ),
        )
        self.assertEqual(
            "the observations carry no timestamp",
            observation_age_sentence(None, now=NOW),
        )

    def test_horizon_from_preferences_is_bounded(self) -> None:
        from types import SimpleNamespace

        from founderos_atlas.investigation.state import (
            horizon_minutes_from_preferences,
        )

        self.assertEqual(90, horizon_minutes_from_preferences(
            SimpleNamespace(state_horizon_minutes=90),
        ))
        self.assertEqual(60, horizon_minutes_from_preferences(
            SimpleNamespace(),
        ))
        self.assertEqual(60, horizon_minutes_from_preferences(
            SimpleNamespace(state_horizon_minutes=0),
        ))


# -- S3: the aspect axis ------------------------------------------------------


class AspectAxisTests(unittest.TestCase):
    def test_state_capabilities_are_discovered(self) -> None:
        from founderos_atlas.investigation.validation import (
            ASPECT_STATE,
            capabilities,
        )

        found = {item.subject: item for item in
                 capabilities(aspect=ASPECT_STATE)}
        self.assertEqual({"bgp", "interfaces", "ospf"}, set(found))
        self.assertEqual(("STATE-BGP-001",), found["bgp"].rules)
        self.assertEqual("BGP sessions", found["bgp"].title)
        self.assertEqual("atlas-state-rules@1.0", found["bgp"].pack)

    def test_the_default_aspect_is_configuration(self) -> None:
        """Every PR-172 caller keeps its exact behaviour."""

        from founderos_atlas.investigation.validation import (
            capabilities,
            capability,
        )

        config = {item.subject for item in capabilities()}
        self.assertEqual({"bgp", "ospf"}, config)
        self.assertEqual(
            "configuration", capability("bgp").aspect,
        )

    def test_a_subject_without_a_shape_has_no_state_capability(self) -> None:
        from founderos_atlas.investigation.validation import (
            ASPECT_STATE,
            capability,
        )

        self.assertIsNone(capability("hsrp", aspect=ASPECT_STATE))
        self.assertIsNone(capability("eigrp", aspect=ASPECT_STATE))

    def test_unrealised_names_the_state_half(self) -> None:
        from founderos_atlas.investigation.subjects import SubjectDescriptor
        from founderos_atlas.investigation.validation import (
            ASPECT_STATE,
            unrealised,
        )

        subjects = (SubjectDescriptor(
            "vxlan", "VXLAN", ("vxlan",), state_kind="vxlan-peers",
        ),)
        rows = dict(unrealised(subjects=subjects, aspect=ASPECT_STATE))
        self.assertIn("vxlan", rows)
        self.assertIn("no installed state rule", rows["vxlan"])


# -- S4/S5: the StateRule adapter and the rules as data -----------------------


def _evidence(kind, items, observed_at=NOW):
    from founderos_atlas.reasoning import Evidence

    return Evidence(
        id=f"state:{kind}:ent:r1", kind=kind, source="cli",
        subject="ent:r1", observed_at=observed_at,
        payload={"items": items, "source_commands": ["show bgp summary"]},
    )


class StateRuleAdapterTests(unittest.TestCase):
    def _rule(self, rule_id="STATE-BGP-001"):
        from founderos_atlas.investigation.state_rules import (
            StateRule,
            state_rule,
        )

        return StateRule(state_rule(rule_id))

    def test_all_established_passes(self) -> None:
        outcome = self._rule().evaluate((_evidence(
            "bgp-sessions",
            [{"peer_address": "10.0.0.2", "state": "established"}],
        ),), ())
        self.assertEqual("pass", outcome.conclusion_kind)
        self.assertTrue(outcome.applicable)

    def test_an_idle_session_degrades(self) -> None:
        outcome = self._rule().evaluate((_evidence(
            "bgp-sessions",
            [{"peer_address": "10.0.0.2", "state": "established"},
             {"peer_address": "10.0.0.9", "state": "idle"}],
        ),), ())
        self.assertEqual("fail", outcome.conclusion_kind)
        self.assertIn("1 of 2", outcome.conclusion)
        # The offender is named the way an operator would name it.
        statements = " ".join(s.statement for s in outcome.steps)
        self.assertIn("peer 10.0.0.9", statements)

    def test_role_suffixes_are_identity_not_health(self) -> None:
        rule = self._rule("STATE-OSPF-001")
        outcome = rule.evaluate((_evidence(
            "ospf-adjacencies",
            [{"neighbor_router_id": "10.0.0.2", "state": "Full/DR",
              "local_interface": "eth1"},
             {"neighbor_router_id": "10.0.0.3", "state": "Full/BDR",
              "local_interface": "eth2"}],
        ),), ())
        self.assertEqual("pass", outcome.conclusion_kind)

    def test_no_observations_is_not_applicable_never_healthy(self) -> None:
        outcome = self._rule().evaluate((_evidence(
            "bgp-sessions", [],
        ),), ())
        self.assertFalse(outcome.applicable)
        self.assertEqual("pass", outcome.conclusion_kind)  # R2 parity
        self.assertIn("not applicable", outcome.conclusion)

    def test_admin_down_is_excluded_by_name(self) -> None:
        rule = self._rule("STATE-IFACE-001")
        outcome = rule.evaluate((_evidence(
            "interface-status",
            [{"name": "eth1", "state": "up"},
             {"name": "eth2", "state": "admin-down"}],
        ),), ())
        self.assertEqual("pass", outcome.conclusion_kind)
        self.assertIn("1 excluded by name", outcome.conclusion)

    def test_all_admin_down_is_not_applicable(self) -> None:
        rule = self._rule("STATE-IFACE-001")
        outcome = rule.evaluate((_evidence(
            "interface-status",
            [{"name": "eth1", "state": "admin-down"}],
        ),), ())
        self.assertFalse(outcome.applicable)

    def test_no_evidence_is_unknown(self) -> None:
        outcome = self._rule().evaluate((), ())
        self.assertEqual("unknown", outcome.conclusion_kind)
        self.assertFalse(outcome.has_evidence)

    def test_the_inline_predicates_are_gone(self) -> None:
        """Success criterion 4 — the health vocabulary is data."""

        import io

        import founderos_atlas.investigation.engines as engines_module

        source = io.open(
            engines_module.__file__, encoding="utf-8"
        ).read()
        self.assertNotIn("_session_is_established", source)
        self.assertNotIn('startswith("full")', source)

    def test_unstable_is_reserved_and_never_emitted(self) -> None:
        """The word is defined so it cannot be redefined weaker; no
        state projection may produce it (success criterion / R2)."""

        import io

        import founderos_atlas.investigation.validation as validation_module
        from founderos_atlas.investigation.validation import (
            VERDICT_UNSTABLE,
        )

        self.assertEqual("Unstable", VERDICT_UNSTABLE)
        source = io.open(
            validation_module.__file__, encoding="utf-8"
        ).read()
        emit_sites = source.count('"verdict": VERDICT_UNSTABLE')
        self.assertEqual(0, emit_sites)


# -- S6/S7: end-to-end state verdicts ----------------------------------------


def _investigate(question, graph, **kwargs):
    from founderos_atlas.investigation import investigate

    return investigate(question, graph=graph, state_now=NOW, **kwargs)


class StateVerdictEndToEndTests(unittest.TestCase):
    def test_healthy_bgp_reads_healthy_with_the_age(self) -> None:
        graph = _graph_with_bgp(
            [("10.0.0.2", "established"), ("10.0.0.3", "established")],
            contribution_at="2026-08-03T11:54:00+00:00",
        )
        result = _investigate("Is BGP healthy?", graph)
        self.assertIsNotNone(result)
        self.assertEqual("bgp-state", result.plan.template)
        self.assertIn("BGP sessions: Healthy", result.summary)
        self.assertIn("(2 of 2)", result.summary)
        self.assertIn("observed 6 minute(s) ago", result.summary)
        self.assertEqual("High", result.confidence)

    def test_a_down_peer_reads_degraded_and_names_it(self) -> None:
        """The review's flagship sentence shape: observation-level
        counts — one idle peer among established ones is DEGRADED,
        not Failed, even on a single device."""

        graph = _graph_with_bgp(
            [("10.0.0.2", "established"), ("10.0.0.9", "idle")],
        )
        result = _investigate("Are all BGP sessions established?", graph)
        self.assertIn("BGP sessions: Degraded", result.summary)
        self.assertIn("1 of 2 observation(s) in their expected state",
                      result.summary)
        findings = " ".join(
            f"{item.label} {item.detail}" for item in result.findings
        )
        self.assertIn("peer 10.0.0.9", findings)
        self.assertIn("idle", findings)

    def test_every_peer_down_reads_failed(self) -> None:
        graph = _graph_with_bgp(
            [("10.0.0.2", "idle"), ("10.0.0.9", "active")],
        )
        result = _investigate("Is BGP healthy?", graph)
        self.assertIn("BGP sessions: Failed", result.summary)
        self.assertIn("(0 of 2)", result.summary)

    def test_stale_observations_refuse_a_verdict_with_the_age(self) -> None:
        """The headline test (success criterion 2): aged observations
        produce NOT ENOUGH EVIDENCE with the age named — never a
        health verdict."""

        graph = _graph_with_bgp(
            [("10.0.0.2", "established")],
            contribution_at="2026-07-31T12:00:00+00:00",  # 3 days old
        )
        result = _investigate("Is BGP healthy?", graph)
        self.assertIsNotNone(result)
        self.assertNotIn("Healthy", result.summary)
        self.assertIn("could not be judged", result.summary)
        self.assertIn("too old", result.summary)
        self.assertEqual("Unknown", result.confidence)
        gaps = " ".join(result.gaps)
        self.assertIn("observed 3 day(s) ago", gaps)
        self.assertIn("staleness horizon", gaps)

    def test_the_horizon_is_honoured(self) -> None:
        """The horizon is workspace policy: the same evidence that is
        stale under the default (beyond four horizons) is fresh under
        a wider one."""

        five_hours_old = _graph_with_bgp(
            [("10.0.0.2", "established")],
            contribution_at="2026-08-03T07:00:00+00:00",
        )
        stale = _investigate("Is BGP healthy?", five_hours_old)
        self.assertIn("could not be judged", stale.summary)
        self.assertEqual("Unknown", stale.confidence)

        two_hours_old = _graph_with_bgp(
            [("10.0.0.2", "established")],
            contribution_at="2026-08-03T10:00:00+00:00",
        )
        wide = _investigate(
            "Is BGP healthy?", two_hours_old, state_horizon_minutes=180,
        )
        self.assertIn("BGP sessions: Healthy", wide.summary)
        self.assertEqual("High", wide.confidence)

    def test_ageing_evidence_is_stated_and_softens_confidence(self) -> None:
        graph = _graph_with_bgp(
            [("10.0.0.2", "established")],
            contribution_at="2026-08-03T10:00:00+00:00",  # 2 h = ageing
        )
        result = _investigate(
            "Is BGP healthy?", graph, state_horizon_minutes=90,
        )
        self.assertIn("BGP sessions: Healthy", result.summary)
        self.assertIn("ageing", result.summary)
        self.assertEqual("Medium", result.confidence)

    def test_no_speakers_is_not_applicable_never_healthy(self) -> None:
        graph = _Graph(
            devices=(_Device("ent:r1", "r1"),),
            contributions=(_Contribution("Lab", NOW),),
            attributes={"device_metadata": {"ent:r1": {
                "routing_evidence": {"bgp_sessions": [],
                                     "ospf_adjacencies": []},
            }}},
        )
        result = _investigate("Is BGP healthy?", graph)
        self.assertIn("No device in scope runs BGP", result.summary)
        self.assertNotIn("Healthy —", result.summary)
        self.assertEqual("High", result.confidence)

    def test_config_and_state_vocabularies_never_blend(self) -> None:
        graph = _graph_with_bgp([("10.0.0.2", "established")])
        result = _investigate("Is BGP healthy?", graph)
        self.assertNotIn("Compliant", result.summary)
        self.assertNotIn("Non-compliant", result.summary)


# -- S8: honest refusals ------------------------------------------------------


class HonestRefusalTests(unittest.TestCase):
    def test_temporal_questions_are_refused_naming_the_word(self) -> None:
        graph = _graph_with_bgp([("10.0.0.2", "established")])
        for question, word in (
            ("Are interfaces flapping?", "flapping"),
            ("Is BGP stable?", "stable"),
            ("Are OSPF adjacencies unstable?", "unstable"),
        ):
            with self.subTest(question=question):
                result = _investigate(question, graph)
                self.assertIsNotNone(result)
                self.assertEqual(
                    "state-refusal", result.plan.template,
                )
                self.assertIn("state history", result.summary)
                self.assertIn(word, result.summary)
                self.assertEqual("Unknown", result.confidence)
                self.assertNotIn("Healthy", result.summary)

    def test_an_unsupported_subject_names_the_missing_half(self) -> None:
        graph = _graph_with_bgp([("10.0.0.2", "established")])
        result = _investigate("Is HSRP healthy?", graph)
        self.assertIsNotNone(result)
        self.assertIn("no canonical observation shape", result.summary)
        self.assertIn("can currently assess:", result.summary)
        self.assertIn("BGP sessions", result.summary)
        self.assertEqual("Unknown", result.confidence)

    def test_a_missing_rules_half_is_named_differently(self) -> None:
        from unittest.mock import patch

        from founderos_atlas.investigation import subjects as subjects_module
        from founderos_atlas.investigation.models import (
            InvestigationRequest,
        )
        from founderos_atlas.investigation.orchestrator import (
            _state_refusal,
        )

        vxlan = subjects_module.SubjectDescriptor(
            "vxlan", "VXLAN", ("vxlan",), state_kind="vxlan-peers",
        )
        request = InvestigationRequest(
            question="Is VXLAN healthy?", subject="vxlan",
            objective="assess",
        )
        with patch.object(
            subjects_module, "SUBJECT_BY_KEY",
            {**subjects_module.SUBJECT_BY_KEY, "vxlan": vxlan},
        ):
            result = _state_refusal(request, 0.0)
        self.assertIn("no state rules that judge it", result.summary)
        self.assertIn("vxlan-peers", result.summary)

    def test_the_estate_question_is_untouched(self) -> None:
        """The PR-167 estate-wide contract: a question naming nothing
        still reaches Atlas's estate answer (returns None here)."""

        graph = _graph_with_bgp([("10.0.0.2", "established")])
        self.assertIsNone(_investigate("Is the network healthy?", graph))


# -- the synthetic-protocol genericity test (success criterion 5) -------------


class SyntheticProtocolTests(unittest.TestCase):
    def test_adding_a_protocol_is_a_shape_plus_rules(self) -> None:
        """A new protocol's state capability needs only a descriptor
        with a state_kind and a rule judging that kind — no template,
        no engine change, no registry entry."""

        from founderos_atlas.investigation.state_rules import (
            OP_ALL_IN_STATES,
            StateCheck,
            StateRule,
            StateRuleDefinition,
        )
        from founderos_atlas.investigation.subjects import SubjectDescriptor
        from founderos_atlas.investigation.validation import (
            ASPECT_STATE,
            ValidationCapability,
        )

        definition = StateRuleDefinition(
            rule_id="STATE-VXL-001", name="VXLAN peers up",
            description="", subject="vxlan",
            check=StateCheck(
                kind="vxlan-peers", operator=OP_ALL_IN_STATES,
                expected_states=("up",),
            ),
            severity="high", expected_state="Every VTEP peer is up.",
            recommendation="r", remediation="m",
        )
        outcome = StateRule(definition).evaluate((_evidence(
            "vxlan-peers",
            [{"name": "vtep-1", "state": "up"},
             {"name": "vtep-2", "state": "down"}],
        ),), ())
        self.assertEqual("fail", outcome.conclusion_kind)
        self.assertIn("1 of 2", outcome.conclusion)


# -- chip mapping (success criterion 9) --------------------------------------


class StateChipMappingTests(unittest.TestCase):
    def _chip(self, summary: str, confidence: str = "High") -> str:
        from founderos_atlas.advisor.presentation import _verdict

        return _verdict(summary, confidence)["status"]

    def test_state_verdicts_land_on_existing_chips(self) -> None:
        cases = (
            ("BGP sessions: Healthy — every judged observation is in "
             "its expected state (2 of 2 evaluation(s)); observed 6 "
             "minute(s) ago.", "High", "Healthy"),
            ("BGP sessions: Degraded — 1 of 2 judged evaluation(s) "
             "found observations outside their expected state; "
             "observed 6 minute(s) ago.", "High", "Attention required"),
            ("BGP sessions: 1 evaluation(s) below par at medium or low "
             "severity; 1 of 2 judged evaluation(s) pass; observed 6 "
             "minute(s) ago.", "High", "Warning"),
            ("BGP sessions: Failed — no judged observation set is in "
             "its expected state (2 evaluation(s)); observed 6 "
             "minute(s) ago.", "High", "Attention required"),
            ("No device in scope runs BGP — the graph holds no BGP "
             "sessions observations for them. Atlas does not report "
             "absence as health.", "High", "Informational"),
            ("Atlas cannot assess the HSRP operational state — it has "
             "no canonical observation shape for HSRP state. It can "
             "currently assess: BGP sessions, Interface status, OSPF "
             "adjacencies. It will not claim health it has not "
             "checked.", "Unknown", "Informational"),
            ("Atlas cannot judge whether BGP is stable — that needs "
             "state history.", "Unknown", "Informational"),
            ("The BGP sessions could not be judged: the observations "
             "are too old to support a verdict.", "Unknown",
             "Not enough evidence"),
        )
        for summary, confidence, expected in cases:
            with self.subTest(chip=expected, summary=summary[:44]):
                self.assertEqual(
                    expected, self._chip(summary, confidence),
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
