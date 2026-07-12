"""The Cisco IOS / IOS-XE platform driver.

A refactor, not a rewrite: the battle-tested parse-only
``CiscoIOSAdapter`` is reused unchanged behind the generic
``PlatformDriver`` interface, so every existing IOS behavior — command
set, parsing tolerance, identity fallbacks, warnings — is byte-for-byte
identical. Routes are honestly marked not-collected for IOS in this
slice.
"""

from __future__ import annotations

import re

from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.discovery.adapters.cisco_ios import (
    SHOW_INTERFACES,
    SHOW_NEIGHBORS,
    SHOW_VERSION,
)

from ..base import (
    CAP_NOT_COLLECTED,
    CapabilitySpec,
    CapabilityStatus,
    DriverDiscovery,
    PlatformDriver,
)


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
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        # Routes are not collected for IOS yet — stated, never implied.
        return DriverDiscovery(
            result=discovery.result,
            capabilities=(
                *discovery.capabilities,
                CapabilityStatus(
                    "routes", CAP_NOT_COLLECTED,
                    "route collection for IOS is future work",
                ),
            ),
            raw_outputs=discovery.raw_outputs,
        )
