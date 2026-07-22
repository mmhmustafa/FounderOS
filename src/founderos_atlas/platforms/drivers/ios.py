"""The Cisco IOS / IOS-XE platform driver.

A refactor, not a rewrite: the battle-tested parse-only
``CiscoIOSAdapter`` is reused unchanged behind the generic
``PlatformDriver`` interface, so every existing IOS behavior — command
set, parsing tolerance, identity fallbacks, warnings — is byte-for-byte
identical. On top of it the driver captures the routing table: IOS shares
the `show ip route` grammar FRR uses, so the same canonical parser reads
both into one RouteEntry shape.
"""

from __future__ import annotations

from dataclasses import replace
import re

from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.discovery.adapters.cisco_ios import (
    SHOW_INTERFACES,
    SHOW_NEIGHBORS,
    SHOW_VERSION,
)
from founderos_atlas.routing.table import route_table_dicts

from ..base import (
    CAP_COLLECTED,
    CapabilitySpec,
    CapabilityStatus,
    DriverDiscovery,
    PlatformDriver,
)

SHOW_ROUTES = "show ip route"


class CiscoIOSDriver(PlatformDriver):
    platform_id = "cisco-ios"
    display_name = "Cisco IOS / IOS-XE"
    vendor = "cisco"
    probe_command = SHOW_VERSION

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(
            re.search(r"Cisco IOS(?:[ -]XE)? Software", probe_output, re.IGNORECASE)
        )

    @property
    def adapter(self) -> CiscoIOSAdapter:
        return CiscoIOSAdapter()

    def collection_plan(self) -> tuple[CapabilitySpec, ...]:
        return (
            CapabilitySpec("identity", SHOW_VERSION, required=True),
            CapabilitySpec("interfaces", SHOW_INTERFACES, required=True),
            CapabilitySpec("neighbors", SHOW_NEIGHBORS),
            CapabilitySpec("routes", SHOW_ROUTES),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        route_text = discovery.raw_outputs.get(SHOW_ROUTES, "")
        routing_table = route_table_dicts(route_text)
        result = discovery.result
        capabilities = discovery.capabilities
        if routing_table:
            metadata = dict(result.device.metadata)
            metadata["routing_table"] = routing_table
            result = replace(
                result, device=replace(result.device, metadata=metadata)
            )
            # Refine the collection-plan's "routes" status with the count,
            # replacing it rather than appending a duplicate.
            capabilities = tuple(
                CapabilityStatus(
                    "routes", CAP_COLLECTED, f"{len(routing_table)} route(s)"
                )
                if status.name == "routes" else status
                for status in capabilities
            )
        # No route output → the collection plan's own status stands (the
        # command was simply not collected); nothing is implied.
        return DriverDiscovery(
            result=result,
            capabilities=capabilities,
            raw_outputs=discovery.raw_outputs,
        )
