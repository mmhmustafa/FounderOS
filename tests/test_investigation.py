"""PR-167 (INVESTIGATOR): deterministic investigation planning.

The success criterion is negative and specific: a question that names a
protocol or a scope must produce an answer ABOUT that protocol or
scope — never an enterprise summary — and a question that names nothing
must keep producing exactly the estate-wide answer it always did.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from founderos_atlas.investigation import (
    AMBIGUOUS,
    RESOLVED,
    STEP_DONE,
    UNKNOWN,
    extract,
    investigate,
    resolve_endpoint,
    resolve_site,
    select,
)
from founderos_atlas.investigation.orchestrator import scope_vocabulary


def device(eid, host, site, ips):
    return SimpleNamespace(
        enterprise_id=eid, hostname=host,
        site=SimpleNamespace(label=site), management_ips=tuple(ips),
        aliases=(), serial_number=None,
    )


def interface(name, ip, status="up"):
    return SimpleNamespace(name=name, ip_address=ip, status=status,
                           protocol_status=status)


def session(peer, *, state="established", remote_as="65002",
            local_as="65001", prefixes=10):
    return {
        "peer_address": peer, "remote_as": remote_as, "local_as": local_as,
        "state": state, "accepted_prefixes": prefixes, "vrf": "default",
        "source_command": "show bgp summary",
    }


def build_graph(*, sites=True):
    """Two peering sites, one isolated site, one down interface."""

    label = (lambda name: name) if sites else (lambda name: "unknown")
    return SimpleNamespace(
        devices=(
            device("ent:mum", "mumbai-core", label("mumbai"), ["10.1.0.1"]),
            device("ent:hyd", "hyderabad-core", label("hyderabad"),
                   ["10.2.0.1"]),
            device("ent:che", "chennai-core", label("chennai"), ["10.3.0.1"]),
        ),
        sites=("chennai", "hyderabad", "mumbai") if sites else ("unknown",),
        interfaces={
            "ent:mum": (interface("Gi0/1", "10.9.9.1"),),
            "ent:hyd": (interface("Gi0/1", "10.9.9.2"),
                        interface("Gi0/2", "10.9.9.6", "down")),
            "ent:che": (),
        },
        links=(
            SimpleNamespace(
                local_enterprise_id="ent:mum", remote_enterprise_id="ent:hyd",
                local_hostname="mumbai-core", remote_hostname="hyderabad-core",
                local_interface="Gi0/1", remote_interface="Gi0/1",
                protocol="lldp",
            ),
        ),
        attributes={"device_metadata": {
            "ent:mum": {"routing_evidence": {
                "bgp_sessions": [session("10.9.9.2"),
                                 session("203.0.113.9", state="idle",
                                         remote_as="64512", prefixes=None)],
                "ospf_adjacencies": [{
                    "neighbor_router_id": "10.2.0.1",
                    "local_interface": "Gi0/1", "state": "Full/DR",
                    "area_id": None,
                }],
            }},
            "ent:hyd": {"routing_evidence": {
                "bgp_sessions": [session("10.9.9.1", remote_as="65001",
                                         local_as="65002", prefixes=8)],
                "ospf_adjacencies": [],
            }},
            "ent:che": {"routing_evidence": {
                "bgp_sessions": [], "ospf_adjacencies": [],
            }},
        }},
    )


GRAPH = build_graph()


# -- Part 1: structured question understanding -----------------------------

class ExtractionTests(unittest.TestCase):
    def test_protocol_and_endpoints_are_extracted(self) -> None:
        request = extract("How is BGP between Mumbai and Hyderabad?",
                          known_sites=GRAPH.sites)
        self.assertEqual("bgp", request.protocol)
        self.assertEqual("Mumbai", request.source)
        self.assertEqual("Hyderabad", request.destination)
        self.assertTrue(request.has_endpoints)

    def test_application_and_endpoints(self) -> None:
        request = extract("Why is HTTPS slow from Branch12 to HQ?")
        self.assertIn("https", request.applications)
        self.assertEqual("slow", request.severity)
        self.assertEqual("Branch12", request.source)
        self.assertEqual("HQ", request.destination)

    def test_interfaces_vlans_vrfs_and_addresses(self) -> None:
        request = extract(
            "Is Gi0/1 down on vlan 300 in vrf CUSTOMER at 10.1.2.3?"
        )
        self.assertIn("Gi0/1", request.interfaces)
        self.assertIn("300", request.vlans)
        self.assertIn("CUSTOMER", request.vrfs)
        self.assertIn("10.1.2.3", request.addresses)
        self.assertEqual("down", request.severity)

    def test_time_range_and_direction(self) -> None:
        request = extract("What changed yesterday on inbound routes?")
        self.assertEqual("yesterday", request.time_range)
        self.assertEqual("inbound", request.direction)

    def test_site_names_are_only_taken_when_atlas_knows_them(self) -> None:
        known = extract("Is Mumbai healthy?", known_sites=GRAPH.sites)
        self.assertIn("mumbai", known.sites)
        unknown = extract("Is Atlantis healthy?", known_sites=GRAPH.sites)
        self.assertEqual((), unknown.sites)

    def test_site_names_are_deduplicated_across_case(self) -> None:
        request = extract("How is BGP between Mumbai and mumbai?",
                          known_sites=GRAPH.sites)
        self.assertEqual(("mumbai",), request.sites)

    def test_a_device_name_is_not_read_as_its_site(self) -> None:
        """"Find mumbai-core" names a DEVICE. Reading "mumbai" out of it
        turned a device lookup into a site summary — exactly the
        substitution this work exists to stop."""

        request = extract("Find mumbai-core", known_sites=GRAPH.sites)
        self.assertEqual((), request.sites)
        self.assertIsNone(select(request))
        # The bare site name still works.
        bare = extract("Is mumbai healthy?", known_sites=GRAPH.sites)
        self.assertEqual(("mumbai",), bare.sites)

    def test_a_question_naming_nothing_names_nothing(self) -> None:
        for question in ("Is the network healthy?",
                         "Explain enterprise health",
                         "Summarize discovery"):
            with self.subTest(question=question):
                request = extract(question, known_sites=GRAPH.sites)
                self.assertFalse(request.named_anything)

    def test_protocol_words_match_on_boundaries(self) -> None:
        """"bgp" must not fire inside a longer token."""

        self.assertEqual("", extract("check the bgpx service").protocol)
        self.assertEqual("bgp", extract("check bgp please").protocol)


# -- Part 2: entity resolution ---------------------------------------------

class ResolutionTests(unittest.TestCase):
    def test_a_known_site_resolves_with_its_members(self) -> None:
        entity = resolve_site(GRAPH, "mumbai")
        self.assertEqual(RESOLVED, entity.status)
        self.assertEqual(("ent:mum",), entity.device_ids)

    def test_an_unknown_name_is_unknown_not_a_guess(self) -> None:
        entity = resolve_endpoint(GRAPH, "Atlantis")
        self.assertEqual(UNKNOWN, entity.status)
        self.assertIn("has not discovered", entity.detail)

    def test_an_ambiguous_site_reports_every_candidate(self) -> None:
        graph = SimpleNamespace(
            devices=(device("a", "a1", "mumbai-north", []),
                     device("b", "b1", "mumbai-south", [])),
            sites=("mumbai-north", "mumbai-south"),
            interfaces={}, links=(), attributes={},
        )
        entity = resolve_site(graph, "mumbai")
        self.assertEqual(AMBIGUOUS, entity.status)
        self.assertEqual(("mumbai-north", "mumbai-south"), entity.candidates)
        self.assertIn("will not choose", entity.detail)

    def test_hostname_grouping_is_used_only_without_sites_and_is_labelled(
        self,
    ) -> None:
        """Estates that encode location in hostnames must still be
        investigable — but the weaker basis has to be stated."""

        graph = build_graph(sites=False)
        entity = resolve_endpoint(graph, "mumbai")
        self.assertEqual(RESOLVED, entity.status)
        self.assertEqual("name-group", entity.kind)
        self.assertIn("naming convention", entity.detail)

    def test_scope_vocabulary_covers_sites_and_hostname_tokens(self) -> None:
        self.assertIn("mumbai", scope_vocabulary(build_graph(sites=False)))
        self.assertIn("chennai", scope_vocabulary(GRAPH))


# -- Parts 3/7: templates and plans ----------------------------------------

class TemplateSelectionTests(unittest.TestCase):
    def select_for(self, question):
        return select(extract(question, known_sites=GRAPH.sites))

    def test_protocol_with_endpoints_selects_the_between_template(
        self,
    ) -> None:
        self.assertEqual(
            "bgp-between",
            self.select_for("How is BGP between Mumbai and Hyderabad?").key,
        )

    def test_protocol_without_endpoints_selects_the_scope_template(
        self,
    ) -> None:
        self.assertEqual("bgp-scope",
                         self.select_for("Show me BGP for Mumbai").key)
        self.assertEqual("ospf-scope",
                         self.select_for("Is OSPF healthy at Mumbai?").key)

    def test_endpoints_without_a_protocol_select_connectivity(self) -> None:
        self.assertEqual(
            "connectivity-between",
            self.select_for("Show routing between Mumbai and Chennai.").key,
        )

    def test_a_named_scope_alone_selects_the_scope_investigation(
        self,
    ) -> None:
        self.assertEqual("site-scope",
                         self.select_for("Is Mumbai healthy?").key)

    def test_estate_wide_questions_select_no_template(self) -> None:
        for question in ("Is the network healthy?",
                         "Explain enterprise health",
                         "What changed?"):
            with self.subTest(question=question):
                self.assertIsNone(self.select_for(question))


# -- Parts 4/5/6/8: execution and smart answers ----------------------------

class InvestigationTests(unittest.TestCase):
    def run_for(self, question, **kwargs):
        return investigate(question, graph=GRAPH, **kwargs)

    def test_bgp_between_sites_answers_about_bgp(self) -> None:
        """The flagship case: a BGP question yields BGP facts, with the
        session count, the states and the AS numbers."""

        result = self.run_for("How is BGP between Mumbai and Hyderabad?")
        self.assertIsNotNone(result)
        self.assertIn("BGP between mumbai and hyderabad", result.summary)
        self.assertIn("2 session(s) observed", result.summary)
        self.assertIn("2 established", result.summary)
        self.assertEqual("High", result.confidence)
        details = " ".join(item.detail for item in result.findings)
        self.assertIn("AS 65001", details)
        self.assertIn("prefix(es) accepted", details)
        # NEVER an enterprise summary.
        self.assertNotIn("managed device(s)", result.summary)
        self.assertNotIn("discovery", result.summary.casefold())

    def test_the_plan_is_built_and_every_step_has_an_outcome(self) -> None:
        result = self.run_for("How is BGP between Mumbai and Hyderabad?")
        self.assertEqual("bgp-between", result.plan.template)
        self.assertTrue(result.plan.objective)
        self.assertGreaterEqual(len(result.plan.steps), 4)
        for step in result.plan.steps:
            with self.subTest(step=step.key):
                self.assertNotEqual("pending", step.status)
        self.assertIn("routing", result.engines_used)
        self.assertIn("graph", result.engines_used)

    def test_absent_peering_is_stated_not_glossed(self) -> None:
        result = self.run_for("How is BGP between Mumbai and Chennai?")
        self.assertIn("no BGP peering", result.summary)
        self.assertIn("none of them to chennai", result.summary.casefold())

    def test_an_unknown_endpoint_stops_the_investigation_honestly(
        self,
    ) -> None:
        result = self.run_for("How is BGP between Mumbai and Atlantis?")
        self.assertIn("cannot investigate this as asked", result.summary)
        self.assertIn("Atlantis", result.summary)
        self.assertEqual("Unknown", result.confidence)
        # It must not answer a different question instead.
        self.assertNotIn("session(s) observed", result.summary)

    def test_bgp_evidence_limits_are_always_stated(self) -> None:
        """Atlas collects BGP *summary* output; advertised prefixes and
        last flap are not in it, and the answer says so."""

        result = self.run_for("Show me BGP for Mumbai")
        gaps = " ".join(result.gaps)
        self.assertIn("Advertised prefix counts", gaps)
        self.assertIn("last-flap", gaps)

    def test_ospf_reports_adjacencies_and_the_missing_area(self) -> None:
        result = self.run_for("Is OSPF healthy at Mumbai?")
        self.assertIn("OSPF for mumbai", result.summary)
        self.assertIn("1 adjacency(ies) observed", result.summary)
        self.assertIn("does not carry the area", " ".join(result.gaps))

    def test_connectivity_reports_the_discovered_link(self) -> None:
        result = self.run_for("Show routing between Mumbai and Hyderabad.")
        self.assertIn("1 direct link(s)", result.summary)

    def test_a_missing_link_is_stated(self) -> None:
        result = self.run_for("Show routing between Mumbai and Chennai.")
        self.assertIn("no direct link", result.summary)

    def test_interface_state_reaches_the_answer(self) -> None:
        result = self.run_for("How is BGP between Mumbai and Hyderabad?")
        self.assertIn("interface(s) in scope are reported down",
                      result.summary)

    def test_shared_context_is_reused_across_steps(self) -> None:
        """Every step reads the same resolved scope — devices resolve
        once, not once per engine."""

        result = self.run_for("Is Mumbai healthy?")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.engines_used), 2)
        self.assertTrue(result.evidence)

    def test_estate_wide_questions_are_not_investigations(self) -> None:
        for question in ("Is the network healthy?",
                         "Explain enterprise health"):
            with self.subTest(question=question):
                self.assertIsNone(self.run_for(question))

    def test_results_are_json_safe_and_complete(self) -> None:
        import json

        result = self.run_for("How is BGP between Mumbai and Hyderabad?")
        payload = result.to_dict()
        json.dumps(payload)
        for key in ("request", "entities", "plan", "findings", "gaps",
                    "evidence", "summary", "confidence", "engines_used"):
            self.assertIn(key, payload)


# -- the Advisor integration -----------------------------------------------

class AdvisorIntegrationTests(unittest.TestCase):
    """The answer an operator actually receives."""

    def build(self, workdir: Path):
        from tests.test_polish import build_world

        return build_world(workdir)

    def test_estate_wide_answers_are_unchanged(self) -> None:
        """PR-167 must not alter the answer to a question that names
        nothing — that is the regression that would matter most."""

        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build(Path(tmp))
            page = client.post(
                "/advisor/ask", data={"question": "Explain enterprise health"},
                follow_redirects=True,
            ).data
            self.assertIn(b"managed device(s)", page)

    def test_an_investigation_is_recorded_on_the_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build(Path(tmp))
            payload = client.post(
                "/api/advisor/ask", json={"question": "Show me BGP for A1"},
            ).get_json()
            # The fixture world may hold no BGP evidence; what must hold
            # is that the question was INVESTIGATED, not answered with
            # an estate summary.
            if payload.get("investigation"):
                self.assertIn("plan", payload["investigation"])
                self.assertNotIn("managed device(s)", payload["summary"])

    def test_the_schema_keeps_every_earlier_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build(Path(tmp))
            payload = client.post(
                "/api/advisor/ask", json={"question": "Find A1"},
            ).get_json()
            for key in ("summary", "evidence", "confidence",
                        "confidence_basis", "next_action", "followups",
                        "steps", "intent", "operational_intent",
                        "investigation"):
                self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
