"""API collection coexisting with SSH (FortiOS REST, PAN-OS XML API).

TRANSCRIPT VALIDATED: sanitized captures of real API response shapes.
The tests prove the contract: API evidence MERGES into the SSH driver's
discovery (richer structure wins per section), raw responses are
preserved under ``api:`` keys, and an unreachable API never damages the
CLI evidence already collected.
"""

from __future__ import annotations

import json
import unittest

from founderos_atlas.platforms.api_collectors import (
    FortiOSRestCollector,
    PanOsXmlApiCollector,
)
from founderos_atlas.platforms.drivers import FortiOSDriver, PanOsDriver

from tests.platform_fixtures import fortios as FG
from tests.platform_fixtures import panos as PA


FORTIOS_REST_POLICIES = json.dumps({
    "http_method": "GET", "status": "success",
    "results": [
        {
            "policyid": 1, "name": "trust-to-internet", "status": "enable",
            "action": "accept", "logtraffic": "all",
            "srcintf": [{"name": "trust"}], "dstintf": [{"name": "untrust"}],
            "srcaddr": [{"name": "all"}], "dstaddr": [{"name": "all"}],
            "service": [{"name": "HTTPS"}],
        },
        {
            "policyid": 99, "name": "implicit-deny", "status": "enable",
            "action": "deny",
            "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
            "srcaddr": [{"name": "all"}], "dstaddr": [{"name": "all"}],
            "service": [{"name": "ALL"}],
        },
    ],
})

FORTIOS_REST_VPNS = json.dumps({
    "results": [
        {"name": "to-branch", "rgwy": "198.51.100.1",
         "proxyid": [{"status": "up"}]},
        {"name": "to-dr", "rgwy": "198.51.100.9", "proxyid": []},
    ],
})

FORTIOS_REST_ZONES = json.dumps({
    "results": [
        {"name": "trust", "interface": [
            {"interface-name": "port1"}, {"interface-name": "port3"},
        ]},
        {"name": "untrust", "interface": [{"interface-name": "port2"}]},
    ],
})

PANOS_XML_SYSTEM = """\
<response status="success"><result><system>
  <hostname>sec-fw-01</hostname>
  <serial>013201001234</serial>
  <sw-version>10.2.4-h2</sw-version>
</system></result></response>
"""

PANOS_XML_IPSEC = """\
<response status="success"><result><entries>
  <entry><name>to-branch</name><peerip>198.51.100.9</peerip><state>active</state></entry>
  <entry><name>to-dr-site</name><peerip>198.51.100.33</peerip><state>active</state></entry>
</entries></result></response>
"""


class FakeTransport:
    def __init__(self, outputs: dict, *, unknown: str) -> None:
        self.outputs = dict(outputs)
        self.unknown = unknown

    def execute(self, command: str) -> str:
        return self.outputs.get(command, self.unknown)


def _fortigate_discovery():
    return FortiOSDriver().discover(
        FakeTransport(FG.normal(), unknown=FG.UNKNOWN),
        management_ip_hint="172.20.20.34",
        probe_output=FG.GET_SYSTEM_STATUS,
    )


def _paloalto_discovery():
    return PanOsDriver().discover(
        FakeTransport(PA.normal(), unknown=PA.UNKNOWN),
        management_ip_hint="172.20.20.42",
        probe_output=PA.SHOW_SYSTEM_INFO,
    )


class FortiOSRestTests(unittest.TestCase):
    def _fetch(self, path: str) -> str:
        return {
            FortiOSRestCollector.POLICIES: FORTIOS_REST_POLICIES,
            FortiOSRestCollector.VPNS: FORTIOS_REST_VPNS,
            FortiOSRestCollector.ZONES: FORTIOS_REST_ZONES,
            FortiOSRestCollector.STATUS: json.dumps({"results": {}}),
        }[path]

    def test_api_policies_replace_cli_policies_and_summary_updates(self) -> None:
        discovery = FortiOSRestCollector().collect(
            _fortigate_discovery(), self._fetch
        )
        evidence = discovery.result.device.metadata["firewall_evidence"]
        names = {p["name"] for p in evidence["security_policies"]}
        self.assertEqual({"trust-to-internet", "implicit-deny"}, names)
        self.assertEqual("deny", evidence["summary"]["default_action"])
        self.assertEqual(2, evidence["summary"]["policy_count"])

    def test_raw_api_responses_are_preserved_beside_cli(self) -> None:
        discovery = FortiOSRestCollector().collect(
            _fortigate_discovery(), self._fetch
        )
        self.assertIn("get system status", discovery.raw_outputs)
        self.assertIn(
            f"api:{FortiOSRestCollector.POLICIES}", discovery.raw_outputs
        )
        stamp = discovery.result.device.metadata["api_collection"]
        self.assertEqual("fortios-rest", stamp["channel"])
        self.assertTrue(stamp["merged"])

    def test_cli_sections_survive_where_the_api_had_nothing(self) -> None:
        # The REST collector gathers no NAT endpoint: the CLI's NAT rules
        # and HA evidence must remain untouched by the merge.
        before = _fortigate_discovery()
        nat_before = before.result.device.metadata[
            "firewall_evidence"]["nat_rules"]
        after = FortiOSRestCollector().collect(before, self._fetch)
        evidence = after.result.device.metadata["firewall_evidence"]
        self.assertEqual(len(nat_before), len(evidence["nat_rules"]))
        self.assertEqual("a-p", evidence["ha_mode"])

    def test_an_unreachable_api_never_damages_cli_evidence(self) -> None:
        def broken(path: str) -> str:
            raise ConnectionError("api unreachable")

        before = _fortigate_discovery()
        after = FortiOSRestCollector().collect(before, broken)
        evidence = after.result.device.metadata["firewall_evidence"]
        self.assertEqual(
            dict(before.result.device.metadata["firewall_evidence"]
                 ["summary"]),
            dict(evidence["summary"]),
        )
        self.assertFalse(
            after.result.device.metadata["api_collection"]["merged"]
        )
        self.assertIn(
            "<unavailable:",
            after.raw_outputs[f"api:{FortiOSRestCollector.POLICIES}"],
        )


class PanOsXmlApiTests(unittest.TestCase):
    def _fetch(self, path: str) -> str:
        return {
            PanOsXmlApiCollector.SYSTEM: PANOS_XML_SYSTEM,
            PanOsXmlApiCollector.VPNS: PANOS_XML_IPSEC,
            PanOsXmlApiCollector.HA: "<response/>",
        }[path]

    def test_api_serial_corroborates_and_vpns_merge(self) -> None:
        discovery = PanOsXmlApiCollector().collect(
            _paloalto_discovery(), self._fetch
        )
        metadata = discovery.result.device.metadata
        self.assertEqual("013201001234", metadata["api_serial"])
        self.assertEqual(metadata["api_serial"],
                         discovery.result.device.serial_number)
        vpns = {v["name"]: v["status"]
                for v in metadata["firewall_evidence"]["vpns"]}
        self.assertEqual("active", vpns["to-branch"])

    def test_raw_xml_is_preserved_and_channel_stamped(self) -> None:
        discovery = PanOsXmlApiCollector().collect(
            _paloalto_discovery(), self._fetch
        )
        raw_key = f"api:{PanOsXmlApiCollector.VPNS}"
        self.assertIn(raw_key, discovery.raw_outputs)
        self.assertIn("<entry>", discovery.raw_outputs[raw_key])
        self.assertEqual(
            "panos-xmlapi",
            discovery.result.device.metadata["api_collection"]["channel"],
        )


if __name__ == "__main__":
    unittest.main()
