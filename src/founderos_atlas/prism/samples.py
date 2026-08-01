"""Sample Atlas cases for the PRISM Playground (PR-166.1, Part 1).

A built-in library of realistic investigations, so PRISM can be
demonstrated and evaluated without a live network.

Each sample is written the way Atlas ACTUALLY answers: a deterministic
summary with real counts, the evidence it cited, the checks it ran, an
honest confidence — and what Atlas could NOT determine. Every case
states a limitation on purpose. A sample without one would demonstrate
PRISM against a version of Atlas that does not exist, and would teach
the audience that Atlas answers everything.

These are illustrative fixtures, not captured customer data: the
hostnames and addresses are invented, and no sample is derived from any
real estate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SampleCase:
    """One realistic Atlas investigation, ready to present."""

    key: str
    label: str
    category: str
    confidence: str
    evidence: str
    limitations: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "limitations": self.limitations,
        }


SAMPLE_CASES: tuple[SampleCase, ...] = (
    SampleCase(
        key="bgp-session-down", label="BGP session down", category="Routing",
        confidence="High",
        evidence="""mumbai-core cannot reach chennai-edge over the WAN: the eBGP session to 203.0.113.9 (AS 64512) is in Idle state and has been down for 47 minutes. 12 prefixes previously learned from that peer are withdrawn; traffic is following the backup path through delhi-core, which adds 38 ms.

Evidence Atlas cited:
- Enterprise Graph: federated snapshot 8f2a41c9, 117 managed devices
- BGP Observations: session mumbai-core to 203.0.113.9 state Idle, last established 47m ago
- Change Report: 1 configuration change on mumbai-core 52 minutes ago
- Routing Observations: 12 prefixes withdrawn, backup path via delhi-core active

Checks Atlas performed: Reading the Enterprise Knowledge Graph; Correlating BGP state with the change timeline; Validating the alternate path hop by hop""",
        limitations="Atlas cannot see the peer's side of the session — the remote device is outside the discovered estate, so whether the neighbour also considers the session down is unknown.",
    ),
    SampleCase(
        key="ospf-neighbor-failure", label="OSPF neighbour failure",
        category="Routing", confidence="High",
        evidence="""delhi-dist2 lost its OSPF adjacency with delhi-core on area 0: the neighbour is stuck in ExStart and has been for 3 discovery cycles. The area now has one fewer transit path; delhi-dist2 reaches the core only through delhi-dist1.

Evidence Atlas cited:
- OSPF Observations: neighbour 10.20.0.1 state ExStart, dead timer expiring repeatedly
- Enterprise Graph: MTU 1500 on delhi-dist2 Gi0/2, MTU 9216 on delhi-core Gi1/0/14
- Change Report: MTU on delhi-core Gi1/0/14 changed 2 days ago

Checks Atlas performed: Reading OSPF adjacency state per interface; Comparing interface MTU across the link; Correlating with the configuration change history""",
        limitations="Atlas records the MTU mismatch and the change that introduced it, but does not assert causation — it reports what the evidence shows, not why an engineer made the change.",
    ),
    SampleCase(
        key="interface-down", label="Interface down", category="Access",
        confidence="High",
        evidence="""hyderabad-access1 Gi0/24 is administratively down. 14 access ports on that switch remain up; the affected port previously carried VLAN 210, which has no other member on this device. No traffic has been observed on the port for 6 hours.

Evidence Atlas cited:
- Enterprise Graph: hyderabad-access1, 24 interfaces, 1 administratively down
- Interface Records: Gi0/24 admin down, line protocol down, last change 6h ago
- Change Report: shutdown applied to Gi0/24 6 hours ago

Checks Atlas performed: Reading interface state from the latest discovery; Checking VLAN membership across the site""",
        limitations="Atlas does not know whether the shutdown was intentional. No maintenance window covering this device was recorded in Compass.",
    ),
    SampleCase(
        key="acl-blocking", label="ACL blocking traffic", category="Policy",
        confidence="Medium",
        evidence="""Traffic from the pune user subnet 10.30.4.0/24 to the finance application at 10.10.9.20:443 is denied at pune-fw. Access list OUTSIDE-IN entry 40 denies the source range before entry 90 permits it; entry 40 was added in the most recent change.

Evidence Atlas cited:
- Stored Configurations: pune-fw access list OUTSIDE-IN, 118 entries
- Path Evidence: pune-user-1 to 10.10.9.20 stops at pune-fw, matched entry 40
- Change Report: 3 access-list entries added to pune-fw 4 hours ago

Checks Atlas performed: Walking the path hop by hop against captured routing tables; Evaluating access lists on the path in order""",
        limitations="Atlas evaluates the configuration as captured 4 hours ago. It cannot confirm live counters, so it cannot say how many sessions were actually dropped.",
    ),
    SampleCase(
        key="vpn-tunnel-failure", label="VPN tunnel failure",
        category="Connectivity", confidence="Medium",
        evidence="""The site-to-site tunnel between bengaluru-edge and the datacentre concentrator is down. Phase 1 completes; phase 2 fails with a proxy-identity mismatch. The branch has been falling back to the internet path for 2 hours, which is not encrypted for this application.

Evidence Atlas cited:
- Stored Configurations: bengaluru-edge crypto map, 1 peer, 2 proxy identities
- Enterprise Graph: bengaluru-edge tunnel interface down, backup route active
- Change Report: encryption domain edited on the concentrator 3 hours ago

Checks Atlas performed: Reading tunnel state from the latest discovery; Comparing proxy identities on both ends where both were discovered""",
        limitations="The concentrator is only partially discovered — credentials were refused on its management interface, so Atlas compared the branch configuration against a 5-day-old capture of the far end.",
    ),
    SampleCase(
        key="high-cpu", label="High CPU", category="Device health",
        confidence="Low",
        evidence="""chennai-core reported 94% CPU utilisation at the last discovery. The process consuming most of it is the routing process. This device holds 41 BGP sessions, the most of any device in the estate, and 3 of them have changed state in the past hour.

Evidence Atlas cited:
- Enterprise Graph: chennai-core, 41 BGP sessions, 12 OSPF adjacencies
- Device Health: CPU 94% at last poll, memory 61%
- Routing Observations: 3 sessions with recent state changes

Checks Atlas performed: Reading device health from the latest discovery; Counting routing adjacencies per device""",
        limitations="Atlas holds a single CPU reading from the last discovery, not a trend. It cannot say whether this is a spike or a sustained condition, and it holds no per-process breakdown.",
    ),
    SampleCase(
        key="memory-exhaustion", label="Memory exhaustion",
        category="Device health", confidence="Medium",
        evidence="""kolkata-dist1 is at 89% memory utilisation and has logged 4 allocation failures since the previous discovery. The device holds the full internet table from two providers, which it did not hold at the previous capture.

Evidence Atlas cited:
- Device Health: memory 89%, 4 allocation failures
- Routing Observations: 1,024,318 prefixes in the routing table, up from 512,004
- Change Report: a second provider session was configured 1 day ago

Checks Atlas performed: Reading device health and table sizes; Comparing prefix counts against the previous discovery""",
        limitations="Atlas cannot predict when the device will exhaust memory — it holds two data points, not a growth model, and does not know the platform's actual ceiling.",
    ),
    SampleCase(
        key="port-flapping", label="Port flapping", category="Access",
        confidence="High",
        evidence="""mumbai-access3 Gi0/11 has changed state 27 times in the last hour. The port connects to a wiring-closet uplink; each transition withdraws 6 MAC addresses and triggers a spanning-tree recalculation on the access VLAN.

Evidence Atlas cited:
- Interface Records: Gi0/11, 27 state transitions in 60 minutes
- Enterprise Graph: 6 endpoints learned on Gi0/11
- Change Report: no configuration change on this device in 14 days

Checks Atlas performed: Reading interface transition counters; Checking the change history for this device""",
        limitations="Atlas records transitions but holds no optical or error-counter telemetry, so it cannot distinguish a failing transceiver from a cable fault or a device on the far end rebooting.",
    ),
    SampleCase(
        key="stp-topology-change", label="STP topology change",
        category="Access", confidence="Medium",
        evidence="""The spanning-tree root for VLAN 300 moved from delhi-dist1 to delhi-access2 at some point in the last discovery interval. An access-layer switch is now the root bridge for that VLAN, and traffic between the distribution pair crosses the access layer.

Evidence Atlas cited:
- Enterprise Graph: VLAN 300 root bridge delhi-access2, priority 32768
- Stored Configurations: delhi-dist1 root priority not configured for VLAN 300
- Change Report: VLAN 300 added to the access layer 1 day ago

Checks Atlas performed: Reading spanning-tree state per VLAN; Comparing configured bridge priorities across the site""",
        limitations="Atlas sees the current root, not the moment it moved. Without a topology-change history it cannot say how many times the root changed or exactly when.",
    ),
    SampleCase(
        key="hsrp-failover", label="HSRP failover", category="Connectivity",
        confidence="High",
        evidence="""The HSRP active router for the pune server VLAN is now pune-dist2. pune-dist1, the configured primary, is in Standby. The tracked uplink on pune-dist1 is down, which decremented its priority below the standby's.

Evidence Atlas cited:
- Enterprise Graph: HSRP group 10, active pune-dist2, standby pune-dist1
- Interface Records: pune-dist1 Gi1/0/1 down (the tracked interface)
- Stored Configurations: pune-dist1 standby 10 track Gi1/0/1 decrement 30

Checks Atlas performed: Reading first-hop redundancy state; Correlating tracked-interface state with configured priorities""",
        limitations="The failover behaved as configured; whether the underlying uplink failure is resolved is a separate question Atlas has not been asked and cannot infer.",
    ),
    SampleCase(
        key="routing-loop", label="Routing loop", category="Routing",
        confidence="Medium",
        evidence="""Traffic to 10.55.12.0/24 alternates between delhi-core and delhi-dist1 without reaching a destination. delhi-core has a static route pointing at delhi-dist1; delhi-dist1 has a default route pointing back at delhi-core, and neither device holds a more specific route for the prefix.

Evidence Atlas cited:
- Routing Tables: delhi-core static 10.55.12.0/24 via delhi-dist1
- Routing Tables: delhi-dist1 default 0.0.0.0/0 via delhi-core, no specific match
- Path Evidence: delhi-core to delhi-dist1 to delhi-core, repeated

Checks Atlas performed: Walking the path against captured routing tables; Stopping at the first repeated hop rather than continuing""",
        limitations="The prefix 10.55.12.0/24 is not present anywhere in the discovered estate, so Atlas cannot say where it was meant to live or whether the destination exists at all.",
    ),
    SampleCase(
        key="packet-loss", label="Packet loss investigation",
        category="Connectivity", confidence="Low",
        evidence="""An application team reports intermittent loss between the bengaluru office and the datacentre. Atlas confirms the path is up and every hop validated. Two interfaces on the path report input errors: bengaluru-edge Gi0/1 (1,204 errors) and the datacentre-facing port on blr-wan1 (88 errors).

Evidence Atlas cited:
- Path Evidence: bengaluru-user-2 to dc-app-1, 6 hops, all reachable
- Interface Records: 2 interfaces on the path with non-zero input errors
- Enterprise Graph: federated snapshot 8f2a41c9

Checks Atlas performed: Walking the path hop by hop; Reading interface error counters for every hop on the path""",
        limitations="Atlas holds no latency, jitter or loss measurements — it can show the path and error counters, not the user's actual experience. Confirming intermittent loss needs measurement Atlas does not perform.",
    ),
)

SAMPLE_BY_KEY = {case.key: case for case in SAMPLE_CASES}


def sample(key: str) -> SampleCase | None:
    return SAMPLE_BY_KEY.get(key)


def sample_choices() -> list[dict[str, str]]:
    """The selector's options, grouped-ready and ordered as declared."""

    return [
        {"key": case.key, "label": case.label, "category": case.category}
        for case in SAMPLE_CASES
    ]
