"""PR-164 (INTENT) + PR-164.1 (FOUNDATION): the Operational Intent
Router as a hardened platform service.

Pins that detection is deterministic and explained; that the DERIVED
routing table reproduces the Advisor's long-pinned fixed table exactly
(behavioural equivalence across the data-driven refactor); that the
registry lifecycle (register → validate → freeze → route) is enforced;
that validation fails fast and completely; that registration is
capability-owned; and that the public service interface and hardened
analytics behave.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from founderos_atlas.advisor import router as advisor_router
from founderos_atlas.oir import (
    ANALYTICS_SCHEMA_VERSION,
    CAPABILITY_REGISTRARS,
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
    OperationalIntentRouter,
    RegistryFrozenError,
    RegistryValidationError,
    Workflow,
    build_default_registry,
    default_router,
    detect,
)


KNOWN_ENGINES = frozenset((
    ENGINE_HEALTH, ENGINE_CHANGES, ENGINE_DISCOVERY, ENGINE_PATH,
    ENGINE_PREDICTION, ENGINE_COMPASS, ENGINE_CONTINUE, ENGINE_SEARCH,
    ENGINE_ENTERPRISE, ENGINE_INVESTIGATION, ENGINE_UNKNOWN,
))

# The Advisor's long-pinned routing table, reproduced by the DERIVED
# routing table (PR-164.1: the static table is gone; this test is the
# proof the derivation is behaviourally identical, phrase for phrase).
LEGACY_ROUTING_TABLE = (
    (ENGINE_CONTINUE, ("continue", "resume", "pick up where")),
    (ENGINE_PREDICTION, (
        "what happens if", "what would happen", "predict", "impact of",
        "blast radius", "if i disable", "if i shut", "if we disable",
        "if we shut", "if i reboot", "if i upgrade",
    )),
    (ENGINE_PATH, (
        "cannot reach", "can't reach", "cant reach", "unable to reach",
        "not reachable", "unreachable from", "reach", "connectivity",
        "path from", "path between", "path to",
    )),
    (ENGINE_COMPASS, (
        "maintenance", "plan a change", "help me plan", "plan tonight",
        "change window", "maintenance window", "execution order",
    )),
    (ENGINE_CHANGES, (
        "what changed", "changed today", "changed overnight",
        "changed since", "recent changes", "any changes", "changes",
    )),
    (ENGINE_HEALTH, (
        "health", "healthy", "how is the enterprise", "how is the network",
        "status of the enterprise",
        "problem", "problems", "any issue", "issues", "anything wrong",
        "what's wrong", "whats wrong", "is anything wrong", "any concern",
        "is the network fine", "network fine", "is everything fine",
        "everything fine", "is everything ok", "everything ok",
        "everything okay", "all good", "is it healthy",
        "is everything healthy",
        "anything critical", "any critical", "is anything critical",
        "any risk", "any risks", "are there risks", "what are the risks",
        "top risks", "how is ", "how healthy", "is it okay", "is it ok",
        "is it fine", "any alerts", "anything to worry", "should i worry",
    )),
    (ENGINE_DISCOVERY, (
        "run discovery", "run a discovery", "start discovery",
        "resume discovery", "discover ", "scan ", "onboard",
        "summarize discovery", "discovery summary", "last discovery",
        "latest discovery", "discovery", "discovered",
    )),
    (ENGINE_INVESTIGATION, (
        "investigation summary", "summarize investigation",
        "last investigation", "latest investigation", "investigations",
        "investigation",
    )),
    (ENGINE_ENTERPRISE, (
        "enterprise summary", "summarize the enterprise",
        "summarize enterprise", "inventory", "how many devices",
        "what is my enterprise",
    )),
    (ENGINE_SEARCH, (
        "find", "search", "where is", "show me", "look up", "locate",
    )),
)

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


def make_intent(**overrides) -> IntentDefinition:
    base = dict(
        name="Example", key="example", description="An example.",
        engine=ENGINE_HEALTH, domain="health", capability="Testing",
        confidence_rule="High on an example phrase.",
    )
    base.update(overrides)
    return IntentDefinition(**base)


class EngineResolutionTests(unittest.TestCase):
    def test_layer_one_reproduces_the_pinned_routing_table(self) -> None:
        for question, engine in PINNED_ENGINES:
            with self.subTest(question=question):
                self.assertEqual(engine, detect(question).engine)

    def test_derived_table_equals_the_legacy_table_verbatim(self) -> None:
        """The strongest equivalence pin: the table DERIVED from
        capability registrations is the old fixed table, engine for
        engine, phrase for phrase, in the same first-match order."""

        derived = tuple(
            (definition.engine, phrases)
            for definition, phrases in DEFAULT_REGISTRY.routing_table()
        )
        self.assertEqual(LEGACY_ROUTING_TABLE, derived)

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
    """Refinement: the finest intent the operator's own words support."""

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

    def test_decorated_keywords_also_anchor_at_word_starts(self) -> None:
        """PR-164.1: "port " must not fire inside "report ", "ge-" not
        inside "edge-", "route " not inside "reroute " — decorated
        single tokens anchor like bare ones; only true multi-word
        phrases match as substrings."""

        report = self.route("Show me the report for chennai-core")
        self.assertEqual("Device Lookup", report.intent.name)
        edge = self.route("Where is the edge-router?")
        self.assertEqual("Device Lookup", edge.intent.name)
        reroute = self.route(
            "How is the network after we reroute traffic?"
        )
        self.assertEqual("Enterprise Health", reroute.intent.name)
        # The decorated forms still fire where they should.
        port = self.route("Find port 2 on chennai-core")
        self.assertEqual("Interface Investigation", port.intent.name)

    def test_search_family_refines_config_and_interfaces(self) -> None:
        config = self.route("Show me the config of SW2")
        self.assertEqual("Configuration Review", config.intent.name)
        self.assertEqual(ENGINE_SEARCH, config.engine)
        interface = self.route("Find eth2 on chennai-core")
        self.assertEqual("Interface Investigation", interface.intent.name)

    def test_no_signal_falls_to_the_engine_default_intent(self) -> None:
        base = self.route("Find SW2.")
        self.assertEqual("Device Lookup", base.intent.name)
        self.assertEqual("High", base.confidence)


class EscalationTests(unittest.TestCase):
    """Fallback keywords rescue questions no direct phrase claims —
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


class RegistryLifecycleTests(unittest.TestCase):
    """PR-164.1 Part 3: register → validate → freeze → route."""

    def test_registration_after_freeze_fails_loudly(self) -> None:
        registry = build_default_registry().freeze()
        with self.assertRaises(RegistryFrozenError) as raised:
            registry.register(make_intent())
        self.assertIn("frozen", str(raised.exception))

    def test_routing_requires_a_frozen_registry(self) -> None:
        registry = build_default_registry()  # open: not yet frozen
        with self.assertRaises(RegistryFrozenError):
            detect("Is the network healthy?", registry=registry)

    def test_freeze_is_idempotent(self) -> None:
        registry = build_default_registry()
        self.assertIs(registry.freeze(), registry.freeze())
        self.assertTrue(registry.frozen)

    def test_registry_version_is_deterministic_content_hash(self) -> None:
        first = build_default_registry().freeze()
        second = build_default_registry().freeze()
        self.assertTrue(first.version)
        self.assertEqual(first.version, second.version)

    def test_registry_version_sees_every_routing_relevant_field(self) -> None:
        """A catalog that ROUTES differently must VERSION differently —
        fallback/refine keywords drive detection, so they hash."""

        registry = build_default_registry()
        registry.register(make_intent(
            key="probe", name="Probe", fallback_keywords=("probeword",),
        ))
        changed = registry.freeze().version
        baseline = build_default_registry()
        baseline.register(make_intent(key="probe", name="Probe"))
        self.assertNotEqual(baseline.freeze().version, changed)

    def test_default_router_first_call_is_thread_safe(self) -> None:
        """Concurrent first calls must all get the SAME frozen router —
        never a false 'circular registration' error (the pre-hardening
        failure mode on a threaded server's first requests)."""

        from founderos_atlas.oir import service

        original = service._default_router
        service._default_router = None
        try:
            barrier = threading.Barrier(4)
            routers: list = []
            errors: list = []

            def hit() -> None:
                barrier.wait()
                try:
                    routers.append(default_router())
                except Exception as error:  # noqa: BLE001 - the assert
                    errors.append(error)

            threads = [threading.Thread(target=hit) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            self.assertEqual([], errors)
            self.assertEqual(4, len(routers))
            self.assertEqual(1, len({id(router) for router in routers}))
        finally:
            service._default_router = original

    def test_importing_the_package_alone_stays_lazy(self) -> None:
        """`import founderos_atlas.oir` must not build the catalog —
        the capability registrars load at first ROUTE, not at import
        (and the lazy names stay out of __all__ so star-imports cannot
        trigger the build either)."""

        code = (
            "import founderos_atlas.oir as oir\n"
            "import founderos_atlas.oir.service as service\n"
            "assert service._default_router is None, 'built at import'\n"
            "assert 'DEFAULT_REGISTRY' not in oir.__all__\n"
            "assert 'ENGINE_RULES' not in oir.__all__\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={"PYTHONPATH": "src", "SYSTEMROOT": "C:\\Windows"},
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        self.assertEqual(0, completed.returncode, completed.stderr)


class RegistryValidationTests(unittest.TestCase):
    """PR-164.1 Part 5: fail fast, fail loud, fail completely."""

    def freeze_expecting(self, *definitions) -> RegistryValidationError:
        registry = IntentRegistry()
        for definition in definitions:
            registry.register(definition)
        with self.assertRaises(RegistryValidationError) as raised:
            registry.freeze()
        return raised.exception

    def valid_pair(self, **overrides):
        default = make_intent(
            key="base", name="Base", default_for_engine=True,
            routing_phrases=("base phrase",), routing_priority=10,
        )
        other = make_intent(**overrides)
        return default, other

    def test_duplicate_routing_phrases_are_refused(self) -> None:
        error = self.freeze_expecting(*self.valid_pair(
            key="clash", name="Clash",
            routing_phrases=("base phrase",), routing_priority=20,
        ))
        self.assertTrue(
            any("already claimed" in problem for problem in error.problems)
        )

    def test_conflicting_priorities_are_refused(self) -> None:
        error = self.freeze_expecting(*self.valid_pair(
            key="clash", name="Clash",
            routing_phrases=("another phrase",), routing_priority=10,
        ))
        self.assertTrue(
            any("conflicts" in problem for problem in error.problems)
        )

    def test_unknown_workflow_references_are_refused(self) -> None:
        error = self.freeze_expecting(*self.valid_pair(
            key="typo", name="Typo",
            workflows=(Workflow("Open", "/topolgy", "why"),),
        ))
        self.assertTrue(
            any("unknown workflow reference" in problem
                for problem in error.problems)
        )

    def test_unknown_evidence_kinds_are_refused(self) -> None:
        error = self.freeze_expecting(*self.valid_pair(
            key="typo", name="Typo",
            required_evidence=("Enterprise Grpah",),
        ))
        self.assertTrue(
            any("unknown evidence kind" in problem
                for problem in error.problems)
        )

    def test_an_engine_needs_exactly_one_default(self) -> None:
        none = self.freeze_expecting(make_intent())
        self.assertTrue(
            any("no intent declares" in problem for problem in none.problems)
        )
        two = self.freeze_expecting(
            make_intent(key="a", name="A", default_for_engine=True),
            make_intent(key="b", name="B", default_for_engine=True),
        )
        self.assertTrue(
            any("exactly one is allowed" in problem
                for problem in two.problems)
        )

    def test_every_problem_is_reported_in_one_pass(self) -> None:
        error = self.freeze_expecting(make_intent(
            key="mess", name="Mess",
            routing_phrases=("x",),          # priority missing
            workflows=(Workflow("Open", "/nope", "why"),),
            required_evidence=("Nope",),
        ))
        self.assertGreaterEqual(len(error.problems), 3)

    def test_duplicate_keys_are_refused_at_registration(self) -> None:
        registry = IntentRegistry()
        registry.register(make_intent())
        with self.assertRaises(RegistryValidationError):
            registry.register(make_intent())

    def test_mixed_case_routing_phrases_are_refused(self) -> None:
        """Questions are casefolded before matching; a mixed-case
        phrase would pass silently and never fire — a dead route."""

        error = self.freeze_expecting(make_intent(
            default_for_engine=True,
            routing_phrases=("BGP status",), routing_priority=10,
        ))
        self.assertTrue(
            any("must be lowercase" in problem
                for problem in error.problems)
        )

    def test_non_string_tuple_entries_are_refused(self) -> None:
        error = self.freeze_expecting(make_intent(
            default_for_engine=True,
            limitations=({"a set"},),
        ))
        self.assertTrue(
            any("must be a string" in problem
                for problem in error.problems)
        )

    def test_unserialisable_declarations_fail_as_validation_errors(
        self,
    ) -> None:
        """Even a value the field checks miss must surface as the
        documented RegistryValidationError — never a raw TypeError —
        before any derived state exists, leaving the registry open."""

        registry = IntentRegistry()
        # A set passes the required-field check (str() of it is
        # non-empty) and no tuple-field check covers confidence_rule —
        # only json.dumps refuses it, which is the guard under test.
        registry.register(make_intent(
            default_for_engine=True,
            confidence_rule={"a set, not a string"},
        ))
        with self.assertRaises(RegistryValidationError) as raised:
            registry.freeze()
        self.assertIn("not JSON-serialisable", str(raised.exception))
        self.assertFalse(registry.frozen)
        with self.assertRaises(RegistryFrozenError):
            registry.routing_table()  # no half-derived state is readable

    def test_the_unknown_key_must_be_the_unknown_engine(self) -> None:
        error = self.freeze_expecting(make_intent(
            key="unknown", name="Odd", default_for_engine=True,
        ))
        self.assertTrue(
            any("honest fallback" in problem for problem in error.problems)
        )


class ServiceInterfaceTests(unittest.TestCase):
    """PR-164.1 Part 6: consumers depend on OperationalIntentRouter."""

    def test_the_public_router_resolves_the_pinned_battery(self) -> None:
        router = OperationalIntentRouter()
        for question, engine in PINNED_ENGINES:
            with self.subTest(question=question):
                self.assertEqual(engine, router.route(question).engine)

    def test_default_router_is_a_frozen_singleton(self) -> None:
        router = default_router()
        self.assertIs(router, default_router())
        self.assertTrue(router.registry.frozen)

    def test_intent_lookup_reads_the_catalog(self) -> None:
        router = default_router()
        self.assertEqual(
            "Connectivity Validation",
            router.intent("connectivity-validation").name,
        )
        self.assertIsNone(router.intent("nope"))
        self.assertGreaterEqual(len(router.intents()), 25)

    def test_diagnostics_describe_the_frozen_registry(self) -> None:
        report = default_router().diagnostics()
        self.assertTrue(report["registry_version"])
        self.assertTrue(report["frozen"])
        self.assertEqual("passed", report["validation"])
        self.assertGreaterEqual(report["intent_count"], 25)
        self.assertIn("Path Intelligence", report["capabilities"])
        self.assertEqual(
            [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            [row["priority"] for row in report["routing_table"]],
        )
        self.assertEqual(
            "device-lookup", report["engine_defaults"][ENGINE_SEARCH]
        )
        self.assertIn("/paths", report["workflows_referenced"])
        self.assertGreaterEqual(report["startup_ms"], 0)
        # JSON-safe by contract.
        json.dumps(report)


class CapabilityOwnershipTests(unittest.TestCase):
    """PR-164.1 Part 4: registration lives with its owning capability."""

    def test_every_definition_names_its_owning_capability(self) -> None:
        for definition in DEFAULT_REGISTRY.definitions():
            with self.subTest(intent=definition.key):
                self.assertTrue(definition.capability.strip())

    def test_ownership_matches_the_capability_modules(self) -> None:
        owners = {
            definition.key: definition.capability
            for definition in DEFAULT_REGISTRY.definitions()
        }
        self.assertEqual("Path Intelligence",
                         owners["connectivity-validation"])
        self.assertEqual("Routing Intelligence", owners["bgp-investigation"])
        self.assertEqual("Policy", owners["policy-compliance"])
        self.assertEqual("Discovery", owners["discovery-health"])
        self.assertEqual("Identity Resolution", owners["identity-resolution"])
        self.assertEqual("Atlas Platform", owners["unknown"])

    def test_registrars_are_capability_modules_not_a_catalog(self) -> None:
        self.assertGreaterEqual(len(CAPABILITY_REGISTRARS), 14)
        for module_path in CAPABILITY_REGISTRARS:
            self.assertTrue(
                module_path.endswith(".intents")
                or module_path.endswith(".registrations"),
                module_path,
            )

    def test_registration_is_open_to_new_modules(self) -> None:
        """The governance path: a future capability registers a
        definition, the lifecycle freezes it, and detection serves it —
        no new detection code anywhere."""

        registry = build_default_registry()
        registry.register(IntentDefinition(
            name="Backup Review", key="backup-review",
            description="State of configuration backups.",
            engine=ENGINE_CHANGES, domain="configuration",
            capability="Config Memory",
            fallback_keywords=("backup",),
            confidence_rule="Medium — inferred from the keyword.",
        ))
        registry.freeze()
        route = detect("Did the backup run?", registry=registry)
        self.assertEqual("Backup Review", route.intent.name)
        self.assertEqual(ENGINE_CHANGES, route.engine)


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


class AnalyticsTests(unittest.TestCase):
    """Record-only telemetry: bounded, versioned, rotated, tolerant."""

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

    def test_every_record_carries_the_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analytics = IntentAnalytics(Path(tmp))
            analytics.record("detection", {"intent": "x"})
            self.assertEqual(
                ANALYTICS_SCHEMA_VERSION, analytics.entries()[0]["schema"]
            )

    def test_fields_are_bounded_and_non_scalars_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analytics = IntentAnalytics(Path(tmp))
            analytics.record("choice", {
                "href": "/x" * 500,                # truncated
                "nested": {"not": "allowed"},      # dropped
                "listy": [1, 2, 3],                # dropped
                "count": 7,                        # kept
                "rate": float("nan"),              # dropped: not finite
            })
            event = analytics.entries()[0]
            self.assertEqual(300, len(event["href"]))
            self.assertNotIn("nested", event)
            self.assertNotIn("listy", event)
            self.assertNotIn("rate", event)
            self.assertEqual(7, event["count"])

    def test_payload_cannot_forge_the_provenance_markers(self) -> None:
        """schema and kind are the recorder's own stamps — a payload
        carrying those keys must never overwrite them."""

        with tempfile.TemporaryDirectory() as tmp:
            analytics = IntentAnalytics(Path(tmp))
            analytics.record("choice", {"schema": "9.9.9",
                                        "kind": "forged",
                                        "href": "/topology"})
            event = analytics.entries()[0]
            self.assertEqual(ANALYTICS_SCHEMA_VERSION, event["schema"])
            self.assertEqual("choice", event["kind"])

    def test_the_file_rotates_and_keeps_bounded_backups(self) -> None:
        from founderos_atlas.oir import analytics as module

        with tempfile.TemporaryDirectory() as tmp:
            analytics = IntentAnalytics(Path(tmp))
            analytics.record("detection", {"intent": "seed"})
            original_max = module.MAX_FILE_BYTES
            module.MAX_FILE_BYTES = 1  # force rotation on next record
            try:
                analytics.record("detection", {"intent": "second"})
                analytics.record("detection", {"intent": "third"})
            finally:
                module.MAX_FILE_BYTES = original_max
            backup_one = analytics.path.with_name(analytics.path.name + ".1")
            backup_two = analytics.path.with_name(analytics.path.name + ".2")
            self.assertTrue(backup_one.exists())
            self.assertTrue(backup_two.exists())
            # The current file holds only the newest record.
            self.assertEqual(1, len(analytics.entries()))
            self.assertEqual("third", analytics.entries()[0]["intent"])

    def test_missing_file_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], IntentAnalytics(Path(tmp)).entries())


if __name__ == "__main__":
    unittest.main()
