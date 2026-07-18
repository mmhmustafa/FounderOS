"""Cloud network collectors: AWS VPC, Azure VNet, Google Cloud VPC.

Each collector normalizes one cloud's network inventory into canonical
records:

- every VPC / VNet / VPC-network becomes one ``CloudNetworkRecord`` whose
  ``device_role`` is ``cloud-network``;
- its subnets become ``NetworkInterface`` records (the CIDR rides in
  metadata — a subnet has no single address);
- peerings and gateways become ``NetworkNeighbor`` observations, so
  cross-network connectivity flows through the SAME correlation channel
  every physical link uses;
- the untouched API payloads are preserved as raw evidence.

Payloads are the SDK's own response shapes (``describe_vpcs`` JSON,
Azure ARM resource JSON, GCP compute API JSON) supplied by an injected,
already-authenticated client — or read from exported files. No SDK is
imported here.

Maturity: TRANSCRIPT VALIDATED against sanitized captures of real API
response shapes. Never production-claimed without live-account runs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from dataclasses import dataclass, field

from founderos_atlas.discovery.models import (
    NetworkInterface,
    NetworkNeighbor,
)


@dataclass(frozen=True)
class CloudNetworkRecord:
    """The adapter-boundary identity of one cloud network.

    Mirrors ``NetworkDevice`` field-for-field EXCEPT that
    ``management_ip`` may honestly be None — a VPC has no in-band
    management address, and inventing one would be fabricated evidence.
    The core canonical model keeps its strict contract; converting a
    record into a full ``NetworkDevice`` is the integration adapter's
    job once a deployment supplies the management identity.
    """

    device_id: str
    hostname: str
    management_ip: str | None
    vendor: str
    platform: str
    os_name: str
    os_version: str
    serial_number: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "management_ip": self.management_ip,
            "vendor": self.vendor,
            "platform": self.platform,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "serial_number": self.serial_number,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CollectedNetwork:
    """One normalized cloud network: identity + canonical records."""

    device: CloudNetworkRecord
    interfaces: tuple[NetworkInterface, ...] = ()
    neighbors: tuple[NetworkNeighbor, ...] = ()


class CloudCollection:
    """One cloud account's normalized networks plus raw evidence."""

    def __init__(self, results: tuple[CollectedNetwork, ...],
                 raw_outputs: Mapping[str, str]) -> None:
        self.results = results
        self.raw_outputs = dict(raw_outputs)

    @property
    def devices(self) -> tuple[CloudNetworkRecord, ...]:
        return tuple(result.device for result in self.results)


def _tags_name(tags, default: str) -> str:
    for tag in tags or ():
        if tag.get("Key") == "Name" and tag.get("Value"):
            return str(tag["Value"])
    return default


class AwsVpcCollector:
    """AWS VPC evidence from EC2 describe payloads."""

    platform_id = "aws-vpc"
    display_name = "AWS VPC"

    def collect(
        self,
        *,
        vpcs: Mapping[str, Any],
        subnets: Mapping[str, Any] | None = None,
        route_tables: Mapping[str, Any] | None = None,
        peerings: Mapping[str, Any] | None = None,
        internet_gateways: Mapping[str, Any] | None = None,
        region: str = "unknown",
        account_id: str = "unknown",
    ) -> CloudCollection:
        raw = {
            "api:ec2:DescribeVpcs": json.dumps(vpcs, default=str),
            **(
                {"api:ec2:DescribeSubnets": json.dumps(subnets, default=str)}
                if subnets else {}
            ),
            **(
                {"api:ec2:DescribeRouteTables":
                 json.dumps(route_tables, default=str)}
                if route_tables else {}
            ),
            **(
                {"api:ec2:DescribeVpcPeeringConnections":
                 json.dumps(peerings, default=str)}
                if peerings else {}
            ),
            **(
                {"api:ec2:DescribeInternetGateways":
                 json.dumps(internet_gateways, default=str)}
                if internet_gateways else {}
            ),
        }
        subnet_rows = (subnets or {}).get("Subnets") or ()
        peering_rows = (
            (peerings or {}).get("VpcPeeringConnections") or ()
        )
        igw_rows = (
            (internet_gateways or {}).get("InternetGateways") or ()
        )
        route_rows = (route_tables or {}).get("RouteTables") or ()

        results: list[CollectedNetwork] = []
        for vpc in vpcs.get("Vpcs") or ():
            vpc_id = str(vpc.get("VpcId"))
            name = _tags_name(vpc.get("Tags"), vpc_id)
            device_id = f"aws-vpc:{vpc_id}"
            own_subnets = [
                s for s in subnet_rows if s.get("VpcId") == vpc_id
            ]
            interfaces = tuple(
                NetworkInterface(
                    name=_tags_name(
                        s.get("Tags"), str(s.get("SubnetId"))
                    ),
                    ip_address=None,
                    status="up" if s.get("State") == "available" else "unknown",
                    metadata={
                        "source_command": "api:ec2:DescribeSubnets",
                        "subnet_id": str(s.get("SubnetId")),
                        "cidr": str(s.get("CidrBlock")),
                        "availability_zone": str(s.get("AvailabilityZone")),
                    },
                )
                for s in own_subnets
            )
            neighbors: list[NetworkNeighbor] = []
            for peering in peering_rows:
                requester = (peering.get("RequesterVpcInfo") or {})
                accepter = (peering.get("AccepterVpcInfo") or {})
                if vpc_id not in (
                    requester.get("VpcId"), accepter.get("VpcId")
                ):
                    continue
                other = (
                    accepter if requester.get("VpcId") == vpc_id
                    else requester
                )
                neighbors.append(NetworkNeighbor(
                    local_device_id=device_id,
                    local_interface=str(
                        peering.get("VpcPeeringConnectionId")
                    ),
                    remote_hostname=f"aws-vpc:{other.get('VpcId')}",
                    protocol="manual",
                    metadata={
                        "observation": "cloud-peering",
                        "peering_id": str(
                            peering.get("VpcPeeringConnectionId")
                        ),
                        "state": str(
                            (peering.get("Status") or {}).get("Code")
                        ),
                        "remote_cidr": str(other.get("CidrBlock")),
                        "management_endpoint": False,
                        "source_command":
                            "api:ec2:DescribeVpcPeeringConnections",
                    },
                ))
            attached_igws = [
                str(igw.get("InternetGatewayId"))
                for igw in igw_rows
                if any(
                    a.get("VpcId") == vpc_id
                    for a in igw.get("Attachments") or ()
                )
            ]
            route_count = sum(
                len(table.get("Routes") or ())
                for table in route_rows
                if table.get("VpcId") == vpc_id
            )
            device = CloudNetworkRecord(
                device_id=device_id,
                hostname=name,
                management_ip=None,
                vendor="aws",
                platform="AWS VPC",
                os_name="aws",
                os_version=region,
                serial_number=vpc_id,
                metadata={
                    "device_role": "cloud-network",
                    "cloud_evidence": {
                        "schema_version": "1.0.0",
                        "provider": "aws",
                        "region": region,
                        "account_id": account_id,
                        "cidr_blocks": [str(vpc.get("CidrBlock"))],
                        "subnet_count": len(own_subnets),
                        "route_count": route_count,
                        "internet_gateways": attached_igws,
                        "is_default": bool(vpc.get("IsDefault")),
                    },
                },
            )
            results.append(CollectedNetwork(
                device=device, interfaces=interfaces,
                neighbors=tuple(neighbors),
            ))
        return CloudCollection(tuple(results), raw)


class AzureVnetCollector:
    """Azure Virtual Network evidence from ARM resource JSON."""

    platform_id = "azure-vnet"
    display_name = "Azure Virtual Network"

    def collect(
        self,
        *,
        virtual_networks: Mapping[str, Any],
        subscription_id: str = "unknown",
    ) -> CloudCollection:
        raw = {
            "api:azure:virtualNetworks":
                json.dumps(virtual_networks, default=str),
        }
        results: list[CollectedNetwork] = []
        for vnet in virtual_networks.get("value") or ():
            name = str(vnet.get("name"))
            properties = vnet.get("properties") or {}
            device_id = f"azure-vnet:{name}"
            interfaces = tuple(
                NetworkInterface(
                    name=str(subnet.get("name")),
                    ip_address=None,
                    status="up",
                    metadata={
                        "source_command": "api:azure:virtualNetworks",
                        "cidr": str(
                            (subnet.get("properties") or {})
                            .get("addressPrefix")
                        ),
                    },
                )
                for subnet in properties.get("subnets") or ()
            )
            neighbors = tuple(
                NetworkNeighbor(
                    local_device_id=device_id,
                    local_interface=str(peering.get("name")),
                    remote_hostname="azure-vnet:" + str(
                        (
                            (peering.get("properties") or {})
                            .get("remoteVirtualNetwork") or {}
                        ).get("id", "").rsplit("/", 1)[-1]
                    ),
                    protocol="manual",
                    metadata={
                        "observation": "cloud-peering",
                        "state": str(
                            (peering.get("properties") or {})
                            .get("peeringState")
                        ),
                        "management_endpoint": False,
                        "source_command": "api:azure:virtualNetworks",
                    },
                )
                for peering in properties.get("virtualNetworkPeerings") or ()
            )
            device = CloudNetworkRecord(
                device_id=device_id,
                hostname=name,
                management_ip=None,
                vendor="azure",
                platform="Azure Virtual Network",
                os_name="azure",
                os_version=str(vnet.get("location", "unknown")),
                serial_number=str(vnet.get("etag", "")) or None,
                metadata={
                    "device_role": "cloud-network",
                    "cloud_evidence": {
                        "schema_version": "1.0.0",
                        "provider": "azure",
                        "region": str(vnet.get("location", "unknown")),
                        "account_id": subscription_id,
                        "cidr_blocks": list(
                            (properties.get("addressSpace") or {})
                            .get("addressPrefixes") or ()
                        ),
                        "subnet_count": len(
                            properties.get("subnets") or ()
                        ),
                    },
                },
            )
            results.append(CollectedNetwork(
                device=device, interfaces=interfaces, neighbors=neighbors,
            ))
        return CloudCollection(tuple(results), raw)


class GcpVpcCollector:
    """Google Cloud VPC evidence from compute API JSON."""

    platform_id = "gcp-vpc"
    display_name = "Google Cloud VPC"

    def collect(
        self,
        *,
        networks: Mapping[str, Any],
        subnetworks: Mapping[str, Any] | None = None,
        project_id: str = "unknown",
    ) -> CloudCollection:
        raw = {
            "api:gcp:networks.list": json.dumps(networks, default=str),
            **(
                {"api:gcp:subnetworks.aggregatedList":
                 json.dumps(subnetworks, default=str)}
                if subnetworks else {}
            ),
        }
        subnet_rows: list[Mapping[str, Any]] = []
        for scope in ((subnetworks or {}).get("items") or {}).values():
            subnet_rows.extend(scope.get("subnetworks") or ())

        results: list[CollectedNetwork] = []
        for network in networks.get("items") or ():
            name = str(network.get("name"))
            device_id = f"gcp-vpc:{name}"
            own = [
                s for s in subnet_rows
                if str(s.get("network", "")).endswith(f"/{name}")
            ]
            interfaces = tuple(
                NetworkInterface(
                    name=str(s.get("name")),
                    ip_address=None,
                    status="up",
                    metadata={
                        "source_command": "api:gcp:subnetworks.aggregatedList",
                        "cidr": str(s.get("ipCidrRange")),
                        "region": str(
                            s.get("region", "").rsplit("/", 1)[-1]
                        ),
                    },
                )
                for s in own
            )
            neighbors = tuple(
                NetworkNeighbor(
                    local_device_id=device_id,
                    local_interface=str(peering.get("name")),
                    remote_hostname="gcp-vpc:" + str(
                        peering.get("network", "").rsplit("/", 1)[-1]
                    ),
                    protocol="manual",
                    metadata={
                        "observation": "cloud-peering",
                        "state": str(peering.get("state")),
                        "management_endpoint": False,
                        "source_command": "api:gcp:networks.list",
                    },
                )
                for peering in network.get("peerings") or ()
            )
            device = CloudNetworkRecord(
                device_id=device_id,
                hostname=name,
                management_ip=None,
                vendor="gcp",
                platform="Google Cloud VPC",
                os_name="gcp",
                os_version="global",
                serial_number=str(network.get("id", "")) or None,
                metadata={
                    "device_role": "cloud-network",
                    "cloud_evidence": {
                        "schema_version": "1.0.0",
                        "provider": "gcp",
                        "region": "global",
                        "account_id": project_id,
                        "cidr_blocks": [
                            str(s.get("ipCidrRange")) for s in own
                        ],
                        "subnet_count": len(own),
                        "auto_create_subnetworks": bool(
                            network.get("autoCreateSubnetworks")
                        ),
                    },
                },
            )
            results.append(CollectedNetwork(
                device=device, interfaces=interfaces, neighbors=neighbors,
            ))
        return CloudCollection(tuple(results), raw)
