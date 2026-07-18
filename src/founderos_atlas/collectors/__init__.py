"""API-native evidence collectors (POLYGLOT Wave 2, Tiers 2 & 4).

Platforms without a CLI dialect — VMware NSX and the cloud networks
(AWS VPC, Azure VNet, Google Cloud VPC) — are collected through their
management APIs and normalized into the SAME canonical models every SSH
driver produces: ``NetworkDevice`` / ``NetworkInterface`` /
``NetworkNeighbor``, with platform evidence in metadata and every raw
API response preserved.

Collectors are client-injected: the caller supplies the SDK client or
fetcher (already authenticated); Atlas ships no cloud credentials, no
HTTP stack and no SDK dependency here. Where the SDK is absent the
collector still works from exported JSON payloads — the evidence
contract is the payload shape, not the transport.

Downstream stays vendor-blind: an AWS VPC peering and an Azure VNet
peering both normalize into neighbor observations; Topology, Policy and
the Evidence Explorer never ask which cloud produced them.
"""

from .cloud import (
    AwsVpcCollector,
    AzureVnetCollector,
    CloudNetworkRecord,
    CollectedNetwork,
    GcpVpcCollector,
)
from .nsx import NsxCollector

__all__ = [
    "AwsVpcCollector",
    "CloudNetworkRecord",
    "CollectedNetwork",
    "AzureVnetCollector",
    "GcpVpcCollector",
    "NsxCollector",
]
