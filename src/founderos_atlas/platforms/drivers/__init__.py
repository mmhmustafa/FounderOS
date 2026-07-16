"""Built-in platform drivers. Each is one class behind ``PlatformDriver``."""

from .atlaslab_firewall import AtlasLabFirewallAdapter, AtlasLabFirewallDriver
from .atlaslab_switch import AtlasLabSwitchAdapter, AtlasLabSwitchDriver
from .frr import FRRoutingAdapter, FRRoutingDriver
from .ios import CiscoIOSDriver

__all__ = [
    "AtlasLabFirewallAdapter",
    "AtlasLabFirewallDriver",
    "AtlasLabSwitchAdapter",
    "AtlasLabSwitchDriver",
    "CiscoIOSDriver",
    "FRRoutingAdapter",
    "FRRoutingDriver",
]
