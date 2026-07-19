"""Packet trace (Phase 2): ACL rules evaluated against declared intent.

The parser reads IOS access-lists (numbered and named, standard and
extended) plus their ``ip access-group`` bindings out of captured
configurations; the engine matches the declared packet (protocol/port,
optionally a source address) against each hop's bound ACLs with
three-valued honesty — match / no-match / cannot-decide — and a definite
deny stops the walk with the exact config line as evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.path_intelligence import investigate_path
from founderos_atlas.path_intelligence.policy import (
    INDETERMINATE,
    canonical_interface,
    evaluate_acl,
    match_rule,
    parse_device_policy,
)

from tests.test_packet_trace import VIEWER
from tests.test_polish import build_world
from tests.test_prediction_architecture import NOW, chain


ACL_CONFIG = """\
hostname SW1
!
ip access-list extended EDGE-IN
 10 permit tcp any any eq 22
 20 deny tcp any any eq 443
 30 permit ip any any
!
interface GigabitEthernet0/1
 ip access-group EDGE-IN in
!
access-list 101 permit tcp any host 10.0.0.10 eq https
access-list 12 permit 10.1.0.0 0.0.255.255
!
end
"""


def sw1_policy():
    return parse_device_policy(
        ACL_CONFIG, hostname="SW1",
        source_path="configs/SW1/running_config.txt",
    )


class AclParserTests(unittest.TestCase):
    def test_named_extended_acl_rules_and_binding(self) -> None:
        policy = sw1_policy()
        rules = policy.rules["EDGE-IN"]
        self.assertEqual(3, len(rules))
        self.assertEqual(
            [("permit", "tcp"), ("deny", "tcp"), ("permit", "ip")],
            [(rule.action, rule.protocol) for rule in rules],
        )
        self.assertEqual((10, 20, 30), tuple(rule.sequence for rule in rules))
        self.assertEqual((443,), rules[1].destination_port.values)
        binding = policy.bindings[0]
        self.assertEqual(
            ("GigabitEthernet0/1", "in", "EDGE-IN"),
            (binding.interface, binding.direction, binding.acl),
        )
        # Every rule cites the exact config line it came from.
        self.assertIn("running_config.txt:5", rules[1].cite(policy.source_path))
        self.assertEqual((), policy.unparsed_acls)

    def test_numbered_and_standard_acls(self) -> None:
        policy = sw1_policy()
        extended = policy.rules["101"][0]
        self.assertEqual("host 10.0.0.10", extended.destination)
        # Service names resolve to ports (eq https -> 443).
        self.assertEqual((443,), extended.destination_port.values)
        standard = policy.rules["12"][0]
        self.assertEqual("ip", standard.protocol)
        self.assertEqual("10.1.0.0 0.0.255.255", standard.source)

    def test_unparseable_rules_are_reported_never_dropped_silently(self) -> None:
        policy = parse_device_policy(
            "ip access-list extended BAD\n 10 permit tcp any\n!\n",
            hostname="X",
        )
        self.assertIn("BAD", policy.unparsed_acls)

    def test_interface_abbreviations_are_one_identity(self) -> None:
        self.assertEqual(
            canonical_interface("GigabitEthernet0/1"),
            canonical_interface("Gi0/1"),
        )
        self.assertNotEqual(
            canonical_interface("Gi0/1"), canonical_interface("Gi0/2")
        )


class AclMatchingTests(unittest.TestCase):
    def test_first_match_wins(self) -> None:
        rules = sw1_policy().rules["EDGE-IN"]
        kind, rule = evaluate_acl(rules, {"protocol": "tcp", "port": "443"})
        self.assertEqual(("deny", 20), (kind, rule.sequence))
        kind, rule = evaluate_acl(rules, {"protocol": "tcp", "port": "22"})
        self.assertEqual(("permit", 10), (kind, rule.sequence))
        # udp/53 falls through both tcp rules to permit ip any any.
        kind, rule = evaluate_acl(rules, {"protocol": "udp", "port": "53"})
        self.assertEqual(("permit", 30), (kind, rule.sequence))

    def test_implicit_deny_when_nothing_matches(self) -> None:
        policy = parse_device_policy(
            "ip access-list extended ONLY-DNS\n 10 permit udp any any eq 53\n",
            hostname="X",
        )
        kind, rule = evaluate_acl(
            policy.rules["ONLY-DNS"], {"protocol": "tcp", "port": "443"}
        )
        self.assertEqual("implicit-deny", kind)
        self.assertIsNone(rule)

    def test_undeclared_facts_are_indeterminate_never_guessed(self) -> None:
        policy = parse_device_policy(
            "ip access-list extended PICKY\n"
            " 10 deny tcp host 10.0.0.5 any eq 443\n"
            " 20 permit ip any any\n",
            hostname="X",
        )
        rules = policy.rules["PICKY"]
        # Without a declared source address the host rule cannot be decided.
        kind, rule = evaluate_acl(rules, {"protocol": "tcp", "port": "443"})
        self.assertEqual((INDETERMINATE, 10), (kind, rule.sequence))
        # Declaring it settles the walk, both ways.
        kind, rule = evaluate_acl(
            rules,
            {"protocol": "tcp", "port": "443", "source_address": "10.0.0.5"},
        )
        self.assertEqual(("deny", 10), (kind, rule.sequence))
        kind, rule = evaluate_acl(
            rules,
            {"protocol": "tcp", "port": "443", "source_address": "10.9.9.9"},
        )
        self.assertEqual(("permit", 20), (kind, rule.sequence))

    def test_unmodeled_qualifiers_are_indeterminate(self) -> None:
        policy = parse_device_policy(
            "ip access-list extended EST\n"
            " 10 permit tcp any any eq 443 established\n",
            hostname="X",
        )
        verdict = match_rule(
            policy.rules["EST"][0], {"protocol": "tcp", "port": "443"}
        )
        self.assertEqual(INDETERMINATE, verdict)


class EnginePolicyTests(unittest.TestCase):
    """chain() fixture: R1 -- SW1 -- SW2; SW1 ingress is Gi0/1."""

    def trace(self, intent, config=ACL_CONFIG):
        policies = {
            "sw1": parse_device_policy(
                config, hostname="SW1",
                source_path="configs/SW1/running_config.txt",
            )
        }
        return investigate_path(
            "R1", "SW2", snapshot=chain(), generated_at=NOW,
            intent=intent, device_policies=policies,
        )

    def test_definite_deny_stops_the_walk_with_cited_rule(self) -> None:
        result = self.trace({"protocol": "tcp", "port": "443"})
        self.assertEqual("failed", result.status)
        self.assertEqual("acl-deny", result.failure_type)
        blocked = result.hops[1]
        self.assertEqual(("SW1", "failed"), (blocked.device, blocked.status))
        self.assertIn("EDGE-IN", blocked.explanation)
        self.assertIn("deny tcp any any eq 443", blocked.explanation)
        self.assertTrue(
            any(
                "configs/SW1/running_config.txt:5" in item
                for item in blocked.evidence
            )
        )
        # The hop after the deny is honestly not evaluated.
        self.assertEqual("unknown", result.hops[2].status)
        self.assertTrue(
            any("access-list" in item for item in result.recommendations)
        )

    def test_permitted_packet_carries_the_permit_as_evidence(self) -> None:
        result = self.trace({"protocol": "tcp", "port": "22"})
        self.assertEqual("connected", result.status)
        self.assertTrue(
            any("permits" in item for item in result.hops[1].evidence)
        )
        policy_basis = result.basis["policy"]
        self.assertEqual(1, policy_basis["hops_evaluated"])
        # R1 and SW2 have no captured configuration — said, not hidden.
        self.assertEqual(["R1", "SW2"], policy_basis["hops_unevaluated"])
        self.assertTrue(
            any("No captured configuration" in item for item in result.unknowns)
        )

    def test_indeterminate_rule_is_a_warning_not_a_verdict(self) -> None:
        config = (
            "hostname SW1\n"
            "!\n"
            "ip access-list extended PICKY\n"
            " 10 deny tcp host 10.0.0.5 any eq 443\n"
            " 20 permit ip any any\n"
            "!\n"
            "interface GigabitEthernet0/1\n"
            " ip access-group PICKY in\n"
            "!\n"
        )
        result = self.trace({"protocol": "tcp", "port": "443"}, config=config)
        self.assertEqual("connected", result.status)
        hop = result.hops[1]
        self.assertEqual("warning", hop.status)
        self.assertTrue(
            any("may apply" in item for item in hop.missing_evidence)
        )

    def test_bound_but_unparsed_acl_is_said_out_loud(self) -> None:
        config = (
            "hostname SW1\n"
            "!\n"
            "ip access-list extended BAD\n"
            " 10 permit tcp any\n"
            "!\n"
            "interface GigabitEthernet0/1\n"
            " ip access-group BAD in\n"
            "!\n"
        )
        result = self.trace({"protocol": "tcp", "port": "443"}, config=config)
        hop = result.hops[1]
        self.assertEqual("warning", hop.status)
        self.assertTrue(
            any("NOT" in item and "BAD" in item for item in hop.missing_evidence)
        )

    def test_no_intent_means_no_policy_claims_at_all(self) -> None:
        result = self.trace(None)
        self.assertEqual("connected", result.status)
        self.assertNotIn("policy", result.basis)


class TraceApiPolicyTests(unittest.TestCase):
    """End-to-end: a config written on disk changes the trace verdict."""

    def _egress_of_first_hop(self, client) -> str:
        body = client.post(
            "/api/paths/trace",
            json={"source": "A1", "destination": "A2"},
        ).get_json()
        return body["hops"][0]["egress_interface"]

    def _write_acl_config(self, workdir: Path, interface: str) -> None:
        config_dirs = {
            path.parent
            for path in workdir.rglob("topology_snapshot.json")
            if "A1" in path.read_text(encoding="utf-8")
        }
        self.assertTrue(config_dirs)
        for scope in config_dirs:
            target = scope / "configs" / "A1"
            target.mkdir(parents=True, exist_ok=True)
            (target / "running_config.txt").write_text(
                "hostname A1\n"
                "!\n"
                "ip access-list extended BLOCK-WEB\n"
                " 10 permit tcp any any eq 22\n"
                " 20 deny tcp any any eq 443\n"
                " 30 permit ip any any\n"
                "!\n"
                f"interface {interface}\n"
                " ip access-group BLOCK-WEB out\n"
                "!\n"
                "end\n",
                encoding="utf-8",
            )

    def test_deny_and_permit_change_the_api_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            egress = self._egress_of_first_hop(client)
            self.assertTrue(egress)
            self._write_acl_config(Path(tmp), egress)

            denied = client.post(
                "/api/paths/trace",
                json={
                    "source": "A1", "destination": "A2",
                    "protocol": "tcp", "port": 443,
                },
            ).get_json()
            self.assertEqual("failed", denied["status"])
            self.assertEqual("acl-deny", denied["failure_type"])
            self.assertIn("BLOCK-WEB", denied["hops"][0]["explanation"])
            self.assertIn("evaluated", denied["intent_note"])

            allowed = client.post(
                "/api/paths/trace",
                json={
                    "source": "A1", "destination": "A2",
                    "protocol": "tcp", "port": 22,
                },
            ).get_json()
            self.assertEqual("connected", allowed["status"])
            # A2 has no captured configuration — the note stays honest.
            self.assertIn("NOT evaluated", allowed["intent_note"])


class ViewerPolicyContractTests(unittest.TestCase):
    def test_viewer_reads_the_policy_summary_not_a_static_caveat(self) -> None:
        viewer = VIEWER.read_text(encoding="utf-8")
        self.assertIn("basis", viewer)
        self.assertIn("hops_evaluated", viewer)


if __name__ == "__main__":
    unittest.main()
