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
from founderos_atlas.routing.policy import (
    parse_ip_policy_bindings,
    parse_route_map_policy_routes,
    policy_route_dicts,
)

from ..base import (
    CAP_COLLECTED,
    CapabilitySpec,
    CapabilityStatus,
    DriverDiscovery,
    PlatformDriver,
)

SHOW_ROUTES = "show ip route"
# Policy routing on IOS takes BOTH commands. `show route-map` gives the
# match and set clauses; `show ip policy` gives which interface each map
# is bound to. A route-map nothing references forwards nothing, so the
# clauses alone would report policy routing on a device applying none.
SHOW_ROUTE_MAP = "show route-map"
SHOW_IP_POLICY = "show ip policy"


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
            CapabilitySpec("policy-routes", SHOW_IP_POLICY),
            CapabilitySpec("policy-route-maps", SHOW_ROUTE_MAP),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        route_text = discovery.raw_outputs.get(SHOW_ROUTES, "")
        routing_table = route_table_dicts(route_text)
        result = discovery.result
        capabilities = discovery.capabilities
        # Policy routes are recorded whenever the BINDING command answered,
        # even when it named nothing. "Asked, and this device policy-routes
        # nothing" is a fact the engine needs; it must not look the same as
        # "never asked", which is this key being absent.
        policy_routes = ()
        policy_captured = SHOW_IP_POLICY in discovery.raw_outputs
        if policy_captured:
            policy_routes = policy_route_dicts(parse_route_map_policy_routes(
                discovery.raw_outputs.get(SHOW_ROUTE_MAP, ""),
                bindings=parse_ip_policy_bindings(
                    discovery.raw_outputs.get(SHOW_IP_POLICY, "")
                ),
                source_command=SHOW_ROUTE_MAP,
            ))
        if routing_table or policy_captured:
            metadata = dict(result.device.metadata)
            if routing_table:
                metadata["routing_table"] = routing_table
            if policy_captured:
                metadata["policy_routes"] = policy_routes
                metadata["policy_routes_captured"] = True
            result = replace(
                result, device=replace(result.device, metadata=metadata)
            )
        if routing_table:
            # Refine the collection-plan's "routes" status with the count,
            # replacing it rather than appending a duplicate. Guarded on the
            # ROUTE table specifically: a device that answered the policy
            # commands but not `show ip route` has collected no routes, and
            # reporting "0 route(s) collected" would say it had.
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
