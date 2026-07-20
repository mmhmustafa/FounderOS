"""Firewall policy joined to the path walk, and the probe's early stop.

A firewall states its policy in the chain it enforces, not in an
access-list. Until this, a trace across a default-deny perimeter found
no ACL evidence at that hop and read as healthy — the one place a
verdict must not be optimistic. Observed live in the multi-city lab:
the deterministic trace said connected while the live probe's packets
died at the site firewall.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from founderos_atlas.console.probe import (
    PING_SETTLED_NOTE,
    SILENT_HOP_LIMIT,
    SILENT_HOP_NOTE,
    silent_tail,
)
from founderos_atlas.path_intelligence import investigate_path
from founderos_atlas.path_intelligence.firewall import (
    evaluate_firewall,
    firewall_from_metadata,
    match_firewall_rule,
)
from founderos_atlas.path_intelligence.policy import INDETERMINATE, NO_MATCH
from founderos_atlas.platforms.drivers.atlaslab_firewall import (
    parse_firewall_rules,
)

from tests.test_prediction_architecture import NOW, chain


# The real chain from the lab's hyderabad perimeter, counters and all.
REAL_CHAIN = """Chain FORWARD (policy DROP 3922 packets, 318K bytes)
num   pkts bytes target     prot opt in     out     source               destination
1        0     0 ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            state RELATED,ESTABLISHED
2      446 93916 ACCEPT     all  --  eth2   eth1    0.0.0.0/0            0.0.0.0/0
3        0     0 ACCEPT     icmp --  eth1   eth2    0.0.0.0/0            10.251.2.2
4        0     0 ACCEPT     icmp --  eth1   eth2    0.0.0.0/0            10.251.2.5
5        0     0 ACCEPT     tcp  --  eth1   eth2    0.0.0.0/0            10.251.2.5           tcp dpt:22
6     3922  318K LOG        all  --  eth1   eth2    0.0.0.0/0            0.0.0.0/0            LOG flags 0 level 4 prefix "ATLASLAB-FW-DROP: "
"""


def real_policy():
    return firewall_from_metadata({"firewall": parse_firewall_rules(REAL_CHAIN)})


class CounterAbbreviationTests(unittest.TestCase):
    """The regression that made Atlas confidently wrong.

    iptables abbreviates a counter once it grows (318K, 2.5M). The rule
    reader demanded plain digits, so the BUSIEST rules — the ones
    actually carrying traffic — silently vanished from the evidence,
    leaving a policy that looked stricter than the enforced one. With
    policy now driving verdicts, a dropped ACCEPT would read as a
    confident deny.
    """

    def test_every_rule_survives_abbreviated_counters(self) -> None:
        parsed = parse_firewall_rules(REAL_CHAIN)
        self.assertEqual(6, parsed["rule_count"])
        rows = [dict(rule) for rule in parsed["rules"]]
        self.assertEqual([1, 2, 3, 4, 5, 6], [r["number"] for r in rows])

    def test_abbreviations_expand_to_numbers(self) -> None:
        parsed = parse_firewall_rules(REAL_CHAIN)
        rows = {dict(r)["number"]: dict(r) for r in parsed["rules"]}
        self.assertEqual(318000, rows[6]["bytes"])
        self.assertEqual(318000, parsed["default_policy_bytes"])
        self.assertEqual(93916, rows[2]["bytes"])

    def test_larger_suffixes_and_decimals(self) -> None:
        text = (
            "Chain FORWARD (policy ACCEPT 1.5M packets, 2G bytes)\n"
            "num   pkts bytes target     prot opt in     out     source               destination\n"
            "1     2.5M   1G ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0\n"
        )
        parsed = parse_firewall_rules(text)
        self.assertEqual(1, parsed["rule_count"])
        self.assertEqual(10**9, dict(parsed["rules"][0])["bytes"])
        self.assertEqual(2 * 10**9, parsed["default_policy_bytes"])


class ChainEvaluationTests(unittest.TestCase):
    def test_the_lab_verdict_matches_what_the_probe_observed(self) -> None:
        # chennai-access1 -> hyderabad-access2 (10.251.2.4) on TCP/443:
        # the lab documents this pair as unreachable by design, and the
        # live traceroute died at this firewall.
        verdict = evaluate_firewall(
            real_policy(), {"protocol": "tcp", "port": "443"},
            ingress="eth1", egress="eth2",
            destination_addresses=("10.251.2.4",),
        )
        self.assertEqual("default-deny", verdict.kind)
        self.assertIn("default policy is DROP", verdict.reason)

    def test_permitted_flows_are_permitted_by_the_right_rule(self) -> None:
        allowed = evaluate_firewall(
            real_policy(), {"protocol": "tcp", "port": "22"},
            ingress="eth1", egress="eth2",
            destination_addresses=("10.251.2.5",),
        )
        self.assertEqual("permit", allowed.kind)
        self.assertEqual(5, allowed.rule.number)
        # The site's own outbound traffic rides rule 2 — the rule the
        # counter bug used to delete.
        outbound = evaluate_firewall(
            real_policy(), {"protocol": "tcp", "port": "443"},
            ingress="eth2", egress="eth1",
            destination_addresses=("8.8.8.8",),
        )
        self.assertEqual("permit", outbound.kind)
        self.assertEqual(2, outbound.rule.number)

    def test_log_is_not_a_verdict(self) -> None:
        """iptables keeps walking after LOG; treating it as terminal
        would invent a permit for everything the chain means to drop."""

        policy = real_policy()
        log_rule = [r for r in policy.rules if r.target == "LOG"][0]
        # It matches the packet...
        self.assertNotEqual(
            NO_MATCH,
            match_firewall_rule(
                log_rule, {"protocol": "tcp", "port": "443"},
                ingress="eth1", egress="eth2",
                destination_addresses=("10.251.2.4",),
            ),
        )
        # ...and the walk still reaches the chain's default policy.
        verdict = evaluate_firewall(
            policy, {"protocol": "tcp", "port": "443"},
            ingress="eth1", egress="eth2",
            destination_addresses=("10.251.2.4",),
        )
        self.assertEqual("default-deny", verdict.kind)

    def test_a_reply_only_rule_cannot_admit_a_new_flow(self) -> None:
        policy = real_policy()
        stateful = [r for r in policy.rules if r.number == 1][0]
        self.assertEqual(
            NO_MATCH,
            match_firewall_rule(
                stateful, {"protocol": "tcp", "port": "443"},
                ingress="eth1", egress="eth2",
                destination_addresses=("10.251.2.4",),
            ),
        )

    def test_undeclared_protocol_is_indeterminate_never_guessed(self) -> None:
        policy = real_policy()
        typed = [r for r in policy.rules if r.number == 5][0]
        self.assertEqual(
            INDETERMINATE,
            match_firewall_rule(
                typed, {"port": "22"},          # no protocol declared
                ingress="eth1", egress="eth2",
                destination_addresses=("10.251.2.5",),
            ),
        )

    def test_a_device_with_no_captured_chain_makes_no_claim(self) -> None:
        self.assertIsNone(firewall_from_metadata(None))
        self.assertIsNone(firewall_from_metadata({}))
        self.assertIsNone(firewall_from_metadata({"firewall": None}))


class EnginePerimeterTests(unittest.TestCase):
    """chain(): R1 -- SW1 -- SW2, with SW1 made a perimeter."""

    def snapshot_with_chain(self, rules_text: str) -> dict:
        snapshot = chain()
        for device in snapshot["devices"]:
            if device["hostname"] == "SW1":
                device["metadata"] = {
                    "firewall": parse_firewall_rules(rules_text)
                }
        return snapshot

    DENY_ALL = """Chain FORWARD (policy DROP 12K packets, 900K bytes)
num   pkts bytes target     prot opt in     out     source               destination
1     4.2M  1G ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            state RELATED,ESTABLISHED
2        0     0 ACCEPT     tcp  --  Gi0/1  Gi0/2   0.0.0.0/0            10.0.0.3             tcp dpt:22
"""

    def test_perimeter_deny_stops_the_walk_with_the_chain_cited(self) -> None:
        result = investigate_path(
            "R1", "SW2", snapshot=self.snapshot_with_chain(self.DENY_ALL),
            generated_at=NOW, intent={"protocol": "tcp", "port": "443"},
        )
        self.assertEqual("failed", result.status)
        self.assertEqual("firewall-deny", result.failure_type)
        blocked = result.hops[1]
        self.assertEqual(("SW1", "failed"), (blocked.device, blocked.status))
        self.assertIn("default policy is DROP", blocked.explanation)
        self.assertTrue(
            any("enforced firewall chain" in item for item in blocked.evidence)
        )
        self.assertEqual("unknown", result.hops[2].status)
        self.assertTrue(
            any("firewall chain" in item for item in result.recommendations)
        )

    def test_a_permitted_packet_crosses_the_same_perimeter(self) -> None:
        result = investigate_path(
            "R1", "SW2", snapshot=self.snapshot_with_chain(self.DENY_ALL),
            generated_at=NOW, intent={"protocol": "tcp", "port": "22"},
        )
        self.assertEqual("connected", result.status)
        self.assertTrue(
            any(
                "enforced firewall chain" in item
                for item in result.hops[1].evidence
            )
        )

    def test_without_declared_intent_no_policy_claim_is_made(self) -> None:
        result = investigate_path(
            "R1", "SW2", snapshot=self.snapshot_with_chain(self.DENY_ALL),
            generated_at=NOW,
        )
        self.assertEqual("connected", result.status)
        self.assertNotIn("policy", result.basis)


class SilentTailTests(unittest.TestCase):
    """A traceroute meeting a device that drops probes never recovers:
    it waits out every remaining hop, minutes at a time."""

    def test_consecutive_silence_ends_the_probe(self) -> None:
        text = (
            "traceroute to 10.251.2.4, 30 hops max\n"
            " 1  10.90.3.5  0.4 ms  0.3 ms  0.3 ms\n"
            " 6  *  *  *\n"
            " 7  *  *  *\n"
            " 8  *  *  *\n"
            " 9 \n"
        )
        self.assertTrue(silent_tail(text, limit=SILENT_HOP_LIMIT))

    def test_answered_hops_do_not_end_it(self) -> None:
        text = (
            "traceroute to 10.251.2.4, 30 hops max\n"
            " 1  10.90.3.5  0.4 ms  0.3 ms  0.3 ms\n"
            " 2  *  *  *\n"
            " 3  10.90.3.1  0.4 ms  0.3 ms  0.3 ms\n"
            " 4  *  *  *\n"
            " 5 \n"
        )
        self.assertFalse(silent_tail(text, limit=SILENT_HOP_LIMIT))

    def test_a_short_trace_is_never_cut_short(self) -> None:
        self.assertFalse(silent_tail("traceroute to x\n 1  *  *  *\n"))
        self.assertFalse(silent_tail(""))

    def test_why_a_probe_stopped_is_the_callers_knowledge(self) -> None:
        """The same early-stop serves a traceroute meeting a black hole
        and a ping that has already answered. Found live: a successful
        ping was annotated 'a device is dropping the probes' — the
        opposite of what had happened."""

        self.assertIn("dropping the probes", SILENT_HOP_NOTE)
        self.assertIn("settle the question", PING_SETTLED_NOTE)
        self.assertNotIn("dropping", PING_SETTLED_NOTE)


if __name__ == "__main__":
    unittest.main()
