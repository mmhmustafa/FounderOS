"""PR-164 (INTENT): the Operational Intent Router.

Pins that detection is deterministic and explained, that the engine
resolution layer reproduces the Advisor's long-pinned routing table,
that refinement and escalation pick the documented intents for the
manual validation set, and that the registry enforces its governance
(one catalog, no duplicate keys, declarations not code).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from founderos_atlas.advisor import router as advisor_router
from founderos_atlas.oir import (
    DEFAULT_REGISTRY,
    ENGINE_CHANGES,
    ENGINE_COMPASS,
    ENGINE_CONTINUE,
    ENGINE_DISCOVERY,
    ENGINE_ENTERPRISE,
    ENGINE_HEALTH,
    ENGINE_INVESTIGATION,
    ENGINE_PATH,
    ENGINE_PREDICTION,
    ENGINE_SEARCH,
    ENGINE_UNKNOWN,
    IntentAnalytics,
    IntentDefinition,
    IntentRegistry,
    build_default_registry,
    detect,
)


KNOWN_ENGINES = frozenset((
    ENGINE_HEALTH, ENGINE_CHANGES, ENGINE_DISCOVERY, ENGINE_PATH,
    ENGINE_PREDICTION, ENGINE_COMPASS, ENGINE_CONTINUE, ENGINE_SEARCH,
    ENGINE_ENTERPRISE, ENGINE_INVESTIGATION, ENGINE_UNKNOWN,
))

# The Advisor's long-pinned routing table, reproduced by OIR Layer 1.
PINNED_ENGINES = (
    ("What changed?", ENGINE_CHANGES),
    ("Find SW1", ENGINE_SEARCH),
    ("Users cannot reach Branch", ENGINE_PATH),
    ("What happens if I disable Gi0/1?", ENGINE_PREDICTION),
    ("Continue yesterday's investigation", ENGINE_CONTINUE),
    ("Help me plan maintenance", ENGINE_COMPASS),
    ("Explain enterprise health", ENGINE_HEALTH),
    ("Summarize discovery", ENGINE_DISCOVERY),
    ("Summarize the enterprise", ENGINE_ENTERPRISE),
    ("What is the meaning of life?", ENGINE_UNKNOWN),
    ("", ENGINE_UNKNOWN),
)


class EngineResolutionTests(unittest.TestCase):
    def test_layer_one_reproduces_the_pinned_routing_table(self) -> None:
        for question, engine in PINNED_ENGINES:
            with self.subTest(question=question):
                self.assertEqual(engine, detect(question).engine)

    def test_advisor_classify_delegates_to_the_oir(self) -> None:
        """One detection engine in Atlas: classify() must agree with
        detect() on every question, including the escalated ones."""

        battery = [question for question, _ in PINNED_ENGINES] + [
            "Why is BGP unstable?", "Can I reboot Core1?",
            "Why is SAP slow?", "Show routing health.",
            "Any identity conflicts?", "Are we policy compliant?",
        ]
        for question in battery:
            with self.subTest(question=question):
                self.assertEqual(
                    detect(question).engine,
                    advisor_router.classify(question),
                )


class RefinementTests(unittest.TestCase):
    """Layer 2: the finest intent the operator's own words support."""

    def route(self, question, **kwargs):
        return detect(question, **kwargs)

    def test_routing_bgp_and_ospf_refine_within_health(self) -> None:
        cases = (
            ("Show routing health.", "Routing Investigation"),
            ("Is BGP healthy?", "BGP Investigation"),
            ("Is OSPF healthy?", "OSPF Investigation"),
            ("Is the WAN healthy?", "WAN Investigation"),
            ("Is the LAN healthy?", "LAN Investigation"),
        )
        for question, intent in cases:
            with self.subTest(question=question):
                route = self.route(question)
                self.assertEqual(intent, route.intent.name)
                self.assertEqual(ENGINE_HEALTH, route.engine)
                self.assertEqual("High", route.confidence)
                self.assertTrue(route.why)

    def test_a_named_known_site_selects_site_health(self) -> None:
        sites = ("mumbai", "chennai")
        named = self.route("Is Mumbai healthy?", sites=sites)
        self.assertEqual("Site Health", named.intent.name)
        self.assertTrue(
            any("mumbai" in reason for reason in named.why)
        )
        # Without known sites the same words are enterprise health —
        # the router refines on KNOWN entities, it never guesses names.
        bare = self.route("Is Mumbai healthy?")
        self.assertEqual("Enterprise Health", bare.intent.name)

    def test_single_word_keywords_match_at_word_starts_only(self) -> None:
        # "plan" must not trip "lan", "Atlanta" must not either.
        plan = self.route("Help me plan maintenance")
        self.assertEqual("Maintenance Planning", plan.intent.name)
        atlanta = self.route("Is Atlanta healthy?")
        self.assertEqual("Enterprise Health", atlanta.intent.name)

    def test_search_family_refines_config_and_interfaces(self) -> None:
        config = self.route("Show me the config of SW2")
        self.assertEqual("Configuration Review", config.intent.name)
        self.assertEqual(ENGINE_SEARCH, config.engine)
        interface = self.route("Find eth2 on chennai-core")
        self.assertEqual("Interface Investigation", interface.intent.name)

    def test_no_signal_falls_to_the_family_base_intent(self) -> None:
        base = self.route("Find SW2.")
        self.assertEqual("Device Lookup", base.intent.name)
        self.assertEqual("High", base.confidence)


class EscalationTests(unittest.TestCase):
    """Fallback keywords rescue questions Layer 1 sends to Unknown —
    at Medium confidence, explained, still deterministic."""

    def test_the_manual_validation_set_routes_as_documented(self) -> None:
        cases = (
            ("Why is BGP unstable?", "BGP Investigation", ENGINE_HEALTH),
            ("Can I reboot Core1?", "Risk Assessment", ENGINE_PREDICTION),
            ("Why is SAP slow?", "Performance Investigation",
             ENGINE_UNKNOWN),
        )
        for question, intent, engine in cases:
            with self.subTest(question=question):
                route = detect(question)
                self.assertEqual(intent, route.intent.name)
                self.assertEqual(engine, route.engine)
                self.assertEqual("Medium", route.confidence)
                self.assertTrue(route.escalated)
                self.assertTrue(route.why)

    def test_performance_intent_carries_its_honest_limitation(self) -> None:
        route = detect("Why is SAP slow?")
        self.assertTrue(route.intent.limitations)
        self.assertIn("telemetry", route.intent.limitations[0].casefold())

    def test_nothing_matched_is_unknown_never_a_guess(self) -> None:
        route = detect("What is the meaning of life?")
        self.assertEqual("Unknown", route.intent.name)
        self.assertEqual("Unknown", route.confidence)
        self.assertFalse(route.escalated)
        route = detect("")
        self.assertEqual("Unknown", route.intent.name)

    def test_detection_is_deterministic(self) -> None:
        for question in ("Why is BGP unstable?", "Is Mumbai healthy?",
                         "Find SW2.", ""):
            first = detect(question, sites=("mumbai",)).to_dict()
            second = detect(question, sites=("mumbai",)).to_dict()
            self.assertEqual(
                json.dumps(first, sort_keys=True),
                json.dumps(second, sort_keys=True),
            )


class CatalogGovernanceTests(unittest.TestCase):
    """One catalog; declarations, not code; honest by construction."""

    def test_every_definition_is_fully_declared(self) -> None:
        for definition in DEFAULT_REGISTRY.definitions():
            with self.subTest(intent=definition.key):
                self.assertTrue(definition.name)
                self.assertTrue(definition.description)
                self.assertIn(definition.engine, KNOWN_ENGINES)
                self.assertTrue(definition.domain)
                self.assertTrue(definition.confidence_rule)
                for workflow in (definition.workflows
                                 + definition.recommendations):
                    self.assertTrue(workflow.label)
                    self.assertTrue(workflow.href.startswith("/"))
                    self.assertTrue(workflow.why)

    def test_the_catalog_covers_the_documented_intent_set(self) -> None:
        names = {item.name for item in DEFAULT_REGISTRY.definitions()}
        for expected in (
            "Enterprise Health", "Site Health", "Connectivity Validation",
            "Routing Investigation", "BGP Investigation",
            "OSPF Investigation", "WAN Investigation", "LAN Investigation",
            "Configuration Review", "Configuration Comparison",
            "Policy Compliance", "Discovery Health", "Identity Resolution",
            "Inventory", "Device Lookup", "Interface Investigation",
            "Performance Investigation", "Security Investigation",
            "Risk Assessment", "Maintenance Planning", "Timeline Review",
            "Change Analysis", "Incident Investigation", "Evidence Lookup",
            "Unknown",
        ):
            self.assertIn(expected, names)

    def test_duplicate_keys_are_refused(self) -> None:
        registry = IntentRegistry()
        definition = IntentDefinition(
            name="Example", key="example", description="x",
            engine=ENGINE_HEALTH, domain="health",
            confidence_rule="High on x.",
        )
        registry.register(definition)
        with self.assertRaises(ValueError):
            registry.register(definition)

    def test_registration_is_open_to_new_modules(self) -> None:
        """The governance path: a future module registers a definition
        and detection serves it — no new detection code anywhere."""

        registry = build_default_registry()
        registry.register(IntentDefinition(
            name="Backup Review", key="backup-review",
            description="State of configuration backups.",
            engine=ENGINE_CHANGES, domain="configuration",
            fallback_keywords=("backup",),
            confidence_rule="Medium — inferred from the keyword.",
        ))
        route = detect("Did the backup run?", registry=registry)
        self.assertEqual("Backup Review", route.intent.name)
        self.assertEqual(ENGINE_CHANGES, route.engine)


class AnalyticsTests(unittest.TestCase):
    """Record-only telemetry: append, read back, never raise."""

    def test_records_round_trip_and_bad_lines_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analytics = IntentAnalytics(Path(tmp))
            analytics.record("detection", {"intent": "Enterprise Health",
                                           "routing_confidence": "High"})
            analytics.record("choice", {"href": "/topology"})
            with analytics.path.open("a", encoding="utf-8") as handle:
                handle.write("this is not json\n")
            events = analytics.entries()
            self.assertEqual(2, len(events))
            self.assertEqual("detection", events[0]["kind"])
            self.assertEqual("/topology", events[1]["href"])

    def test_missing_file_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], IntentAnalytics(Path(tmp)).entries())


if __name__ == "__main__":
    unittest.main()
