"""Built-in platform drivers. Each is one class behind ``PlatformDriver``."""

from .atlaslab_firewall import AtlasLabFirewallAdapter, AtlasLabFirewallDriver
from .atlaslab_switch import AtlasLabSwitchAdapter, AtlasLabSwitchDriver
from .frr import FRRoutingAdapter, FRRoutingDriver
from .ios_xe import CiscoIOSXEAdapter, CiscoIOSXEDriver
from .eos import AristaEOSAdapter, AristaEOSDriver
from .junos import JunosAdapter, JunosDriver
from .nxos import CiscoNXOSAdapter, CiscoNXOSDriver
from .ios import CiscoIOSDriver

__all__ = [
    "AtlasLabFirewallAdapter",
    "AtlasLabFirewallDriver",
    "AtlasLabSwitchAdapter",
    "AtlasLabSwitchDriver",
    "CiscoIOSDriver",
    "CiscoIOSXEAdapter",
    "CiscoIOSXEDriver",
    "CiscoNXOSAdapter",
    "CiscoNXOSDriver",
    "AristaEOSAdapter",
    "AristaEOSDriver",
    "JunosAdapter",
    "JunosDriver",
    "FRRoutingAdapter",
    "FRRoutingDriver",
]
