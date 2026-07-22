"""API-native collectors (NSX, AWS, Azure, GCP) and Tier-2/3 drivers.

TRANSCRIPT VALIDATED: sanitized captures of real API/CLI shapes. The
cross-platform tests prove one canonical form: cloud networks, an SDN
manager, switches, a WLC and three ADCs all produce the same record
kinds with no vendor branching downstream.
"""

from __future__ import annotations

import json
import unittest

from founderos_atlas.collectors import (
    AwsVpcCollector,
    AzureVnetCollector,
    GcpVpcCollector,
    NsxCollector,
)
from founderos_atlas.platforms.drivers import (
    A10AcosDriver,
    ArubaCXDriver,
    CiscoWlcDriver,
    CitrixAdcDriver,
    F5BigIpDriver,
)

from tests.platform_fixtures import adc as ADC
from tests.platform_fixtures import aruba_cx as AR
from tests.platform_fixtures import cisco_wlc as WL


class FakeTransport:
    def __init__(self, outputs: dict, unknown: str) -> None:
        self.outputs, self.unknown = dict(outputs), unknown

    def execute(self, command: str) -> str:
        return self.outputs.get(command, self.unknown)


AWS_VPCS = {
    "Vpcs": [
        {"VpcId": "vpc-0aa1", "CidrBlock": "10.100.0.0/16",
         "IsDefault": False,
         "Tags": [{"Key": "Name", "Value": "prod-vpc"}]},
        {"VpcId": "vpc-0bb2", "CidrBlock": "10.200.0.0/16",
         "IsDefault": False,
         "Tags": [{"Key": "Name", "Value": "shared-vpc"}]},
    ],
}
AWS_SUBNETS = {
    "Subnets": [
        {"SubnetId": "subnet-01", "VpcId": "vpc-0aa1",
         "CidrBlock": "10.100.1.0/24", "AvailabilityZone": "ap-south-1a",
         "State": "available",
         "Tags": [{"Key": "Name", "Value": "prod-app-a"}]},
        {"SubnetId": "subnet-02", "VpcId": "vpc-0aa1",
         "CidrBlock": "10.100.2.0/24", "AvailabilityZone": "ap-south-1b",
         "State": "available"},
    ],
}
AWS_PEERINGS = {
    "VpcPeeringConnections": [
        {"VpcPeeringConnectionId": "pcx-77", "Status": {"Code": "active"},
         "RequesterVpcInfo": {"VpcId": "vpc-0aa1",
                              "CidrBlock": "10.100.0.0/16"},
         "AccepterVpcInfo": {"VpcId": "vpc-0bb2",
                             "CidrBlock": "10.200.0.0/16"}},
    ],
}
AWS_IGWS = {
    "InternetGateways": [
        {"InternetGatewayId": "igw-9",
         "Attachments": [{"VpcId": "vpc-0aa1", "State": "available"}]},
    ],
}

AZURE_VNETS = {
    "value": [
        {
            "name": "hub-vnet", "location": "centralindia",
            "etag": 'W/"abc123"',
            "properties": {
                "addressSpace": {"addressPrefixes": ["10.50.0.0/16"]},
                "subnets": [
                    {"name": "GatewaySubnet",
                     "properties": {"addressPrefix": "10.50.0.0/27"}},
                    {"name": "workload",
                     "properties": {"addressPrefix": "10.50.1.0/24"}},
                ],
                "virtualNetworkPeerings": [
                    {"name": "hub-to-spoke",
                     "properties": {
                         "peeringState": "Connected",
                         "remoteVirtualNetwork": {
                             "id": "/subscriptions/x/providers/"
                                   "Microsoft.Network/virtualNetworks/"
                                   "spoke-vnet",
                         },
                     }},
                ],
            },
        },
    ],
}

GCP_NETWORKS = {
    "items": [
        {"name": "prod-net", "id": "778899",
         "autoCreateSubnetworks": False,
         "peerings": [
             {"name": "prod-to-shared", "state": "ACTIVE",
              "network": "projects/other/global/networks/shared-net"},
         ]},
    ],
}
GCP_SUBNETS = {
    "items": {
        "regions/asia-south1": {
            "subnetworks": [
                {"name": "prod-app",
                 "network": "projects/p/global/networks/prod-net",
                 "ipCidrRange": "10.60.1.0/24",
                 "region": "regions/asia-south1"},
            ],
        },
    },
}

NSX_RESPONSES = {
    "/api/v1/node": json.dumps({
        "hostname": "hyd-nsxmgr-01", "node_version": "4.1.2.1",
        "node_uuid": "3c1f2a2e-1111-2222-3333-444455556666",
    }),
    "/policy/api/v1/infra/tier-0s": json.dumps({
        "results": [{"display_name": "t0-prod", "ha_mode": "ACTIVE_STANDBY"}],
    }),
    "/policy/api/v1/infra/tier-1s": json.dumps({
        "results": [
            {"display_name": "t1-app", "tier0_path": "/infra/tier-0s/t0-prod"},
            {"display_name": "t1-db", "tier0_path": "/infra/tier-0s/t0-prod"},
        ],
    }),
    "/policy/api/v1/infra/segments": json.dumps({
        "results": [
            {"id": "seg-app", "display_name": "seg-app",
             "connectivity_path": "/infra/tier-1s/t1-app",
             "subnets": [{"gateway_address": "10.70.1.1/24"}]},
        ],
    }),
    "/api/v1/transport-nodes": json.dumps({
        "results": [{"id": "tn-1"}, {"id": "tn-2"}, {"id": "tn-3"}],
    }),
}


class AwsVpcTests(unittest.TestCase):
    def _collect(self):
        return AwsVpcCollector().collect(
            vpcs=AWS_VPCS, subnets=AWS_SUBNETS, peerings=AWS_PEERINGS,
            internet_gateways=AWS_IGWS,
            region="ap-south-1", account_id="123456789012",
        )

    def test_each_vpc_is_one_canonical_cloud_network(self) -> None:
        collection = self._collect()
        self.assertEqual(
            {"aws-vpc:vpc-0aa1", "aws-vpc:vpc-0bb2"},
            {d.device_id for d in collection.devices},
        )
        prod = next(
            d for d in collection.devices if d.hostname == "prod-vpc"
        )
        self.assertEqual("cloud-network", prod.metadata["device_role"])
        evidence = prod.metadata["cloud_evidence"]
        self.assertEqual("aws", evidence["provider"])
        self.assertEqual(["10.100.0.0/16"], evidence["cidr_blocks"])
        self.assertEqual(2, evidence["subnet_count"])
        self.assertEqual(["igw-9"], evidence["internet_gateways"])

    def test_subnets_become_interfaces_with_cidr_metadata(self) -> None:
        collection = self._collect()
        prod = next(
            r for r in collection.results
            if r.device.hostname == "prod-vpc"
        )
        by_name = {i.name: i for i in prod.interfaces}
        self.assertEqual(
            "10.100.1.0/24", by_name["prod-app-a"].metadata["cidr"]
        )
        self.assertIsNone(by_name["prod-app-a"].ip_address)

    def test_peerings_are_neighbor_observations_both_ways(self) -> None:
        collection = self._collect()
        peers = {
            result.device.device_id: [
                n.remote_hostname for n in result.neighbors
            ]
            for result in collection.results
        }
        self.assertEqual(["aws-vpc:vpc-0bb2"], peers["aws-vpc:vpc-0aa1"])
        self.assertEqual(["aws-vpc:vpc-0aa1"], peers["aws-vpc:vpc-0bb2"])

    def test_raw_payloads_are_preserved(self) -> None:
        collection = self._collect()
        self.assertIn("api:ec2:DescribeVpcs", collection.raw_outputs)
        self.assertIn("vpc-0aa1", collection.raw_outputs["api:ec2:DescribeVpcs"])


class AzureVnetTests(unittest.TestCase):
    def test_vnet_subnets_and_peering_normalize(self) -> None:
        collection = AzureVnetCollector().collect(
            virtual_networks=AZURE_VNETS, subscription_id="sub-1",
        )
        device = collection.devices[0]
        self.assertEqual("azure-vnet:hub-vnet", device.device_id)
        self.assertEqual(
            ["10.50.0.0/16"],
            device.metadata["cloud_evidence"]["cidr_blocks"],
        )
        result = collection.results[0]
        self.assertEqual(
            {"GatewaySubnet", "workload"},
            {i.name for i in result.interfaces},
        )
        self.assertEqual(
            "azure-vnet:spoke-vnet", result.neighbors[0].remote_hostname
        )
        self.assertEqual(
            "cloud-peering", result.neighbors[0].metadata["observation"]
        )


class GcpVpcTests(unittest.TestCase):
    def test_network_subnets_and_peering_normalize(self) -> None:
        collection = GcpVpcCollector().collect(
            networks=GCP_NETWORKS, subnetworks=GCP_SUBNETS,
            project_id="proj-1",
        )
        device = collection.devices[0]
        self.assertEqual("gcp-vpc:prod-net", device.device_id)
        evidence = device.metadata["cloud_evidence"]
        self.assertEqual("gcp", evidence["provider"])
        self.assertEqual(["10.60.1.0/24"], evidence["cidr_blocks"])
        result = collection.results[0]
        self.assertEqual("prod-app", result.interfaces[0].name)
        self.assertEqual(
            "gcp-vpc:shared-net", result.neighbors[0].remote_hostname
        )


class NsxTests(unittest.TestCase):
    def test_manager_gateways_segments_and_raw_are_normalized(self) -> None:
        collection = NsxCollector().collect(
            NSX_RESPONSES.__getitem__, management_ip="172.20.20.75",
        )
        device = collection.result.device
        self.assertEqual("vmware-nsx:hyd-nsxmgr-01", device.device_id)
        self.assertEqual("4.1.2.1", device.os_version)
        self.assertEqual("sdn-manager", device.metadata["device_role"])
        evidence = device.metadata["nsx_evidence"]
        self.assertEqual(1, len(evidence["tier0_gateways"]))
        self.assertEqual(2, len(evidence["tier1_gateways"]))
        self.assertEqual(1, evidence["segment_count"])
        self.assertEqual(3, evidence["transport_node_count"])
        self.assertEqual(
            "10.70.1.1/24",
            collection.result.interfaces[0].metadata["cidr"],
        )
        self.assertIn("api:/api/v1/node", collection.raw_outputs)

    def test_an_unreachable_endpoint_is_recorded_not_raised(self) -> None:
        def flaky(path: str) -> str:
            if path == "/api/v1/transport-nodes":
                raise ConnectionError("timeout")
            return NSX_RESPONSES[path]

        collection = NsxCollector().collect(flaky)
        self.assertIn(
            "<unavailable:",
            collection.raw_outputs["api:/api/v1/transport-nodes"],
        )
        evidence = collection.result.device.metadata["nsx_evidence"]
        self.assertEqual(0, evidence["transport_node_count"])


class Tier2And3DriverTests(unittest.TestCase):
    def test_aruba_cx_identity_vlans_lag_and_routing(self) -> None:
        discovery = ArubaCXDriver().discover(
            FakeTransport(AR.normal(), AR.UNKNOWN),
            management_ip_hint="172.20.20.60",
            probe_output=AR.SHOW_VERSION,
        )
        device = discovery.result.device
        self.assertEqual("aruba-cx:hyd-agg-01", device.device_id)
        self.assertEqual("SG12KW1234", device.serial_number)
        self.assertEqual("FL.10.11.1021", device.os_version)
        self.assertEqual(
            {"users", "servers", "DEFAULT_VLAN_1"},
            {v["name"] for v in device.metadata["vlans"]},
        )
        self.assertEqual(
            ("1/1/21", "1/1/22"),
            tuple(device.metadata["port_channels"][0]["members"]),
        )
        routing = device.metadata["routing_evidence"]
        self.assertEqual(1, len(routing["ospf_adjacencies"]))
        self.assertEqual("65010", routing["bgp_sessions"][0]["remote_as"])
        self.assertEqual("65060", routing["bgp_sessions"][0]["local_as"])
        # The real RIB, not just the count: Aruba's prefix-line grammar
        # normalizes into the same RouteEntry every platform uses.
        table = {r["prefix"]: r for r in device.metadata["routing_table"]}
        self.assertEqual(device.metadata["route_count"], len(table))
        self.assertEqual(("static", "172.20.20.1"),
                         (table["0.0.0.0/0"]["protocol"],
                          table["0.0.0.0/0"]["next_hop"]))
        # A connected route names its port after "via" and has no next-hop.
        local = table["10.255.0.60/32"]
        self.assertEqual((None, "loopback0", True),
                         (local["next_hop"], local["interface"],
                          local["connected"]))

    def test_wlc_identity_aps_wlans_and_cdp(self) -> None:
        discovery = CiscoWlcDriver().discover(
            FakeTransport(WL.normal(), WL.UNKNOWN),
            management_ip_hint="172.20.20.70",
            probe_output=WL.SHOW_SYSINFO,
        )
        device = discovery.result.device
        self.assertEqual("cisco-wlc:hyd-wlc-01", device.device_id)
        self.assertEqual("FCH2233W0AB", device.serial_number)
        self.assertEqual(
            "wireless-controller", device.metadata["device_role"]
        )
        wireless = device.metadata["wireless_evidence"]
        self.assertEqual(3, wireless["access_point_count"])
        self.assertEqual(213, wireless["client_count"])
        self.assertEqual(4, len(wireless["wlans"]))
        # The wired switch each AP reports through is a CDP neighbor.
        cdp = [n for n in discovery.result.neighbors if n.protocol == "cdp"]
        self.assertTrue(
            all(n.remote_hostname == "hyd-agg-01" for n in cdp)
        )

    def test_f5_citrix_a10_share_the_adc_evidence_shape(self) -> None:
        cases = (
            (F5BigIpDriver(), ADC.f5_normal(), ADC.F5_UNKNOWN,
             "show sys version", "172.20.20.80"),
            (CitrixAdcDriver(), ADC.ns_normal(), ADC.NS_UNKNOWN,
             "show ns version", "172.20.20.90"),
            (A10AcosDriver(), ADC.a10_normal(), ADC.A10_UNKNOWN,
             "show version", "172.20.20.95"),
        )
        for driver, outputs, unknown, probe, hint in cases:
            with self.subTest(platform=driver.platform_id):
                discovery = driver.discover(
                    FakeTransport(outputs, unknown),
                    management_ip_hint=hint,
                    probe_output=outputs[probe],
                )
                device = discovery.result.device
                self.assertEqual(
                    "load-balancer", device.metadata["device_role"]
                )
                evidence = device.metadata["adc_evidence"]
                self.assertEqual(2, evidence["virtual_server_count"])
                self.assertEqual(1, evidence["virtual_servers_up"])
                for item in evidence["virtual_servers"]:
                    self.assertIn(item["state"], ("up", "down"))
                self.assertTrue(device.serial_number)
                self.assertTrue(device.os_version)


if __name__ == "__main__":
    unittest.main()
