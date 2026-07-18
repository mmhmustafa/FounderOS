"""Built-in platform drivers. Each is one class behind ``PlatformDriver``."""

from .atlaslab_firewall import AtlasLabFirewallAdapter, AtlasLabFirewallDriver
from .atlaslab_switch import AtlasLabSwitchAdapter, AtlasLabSwitchDriver
from .adc import (
    A10AcosAdapter,
    A10AcosDriver,
    CitrixAdcAdapter,
    CitrixAdcDriver,
    F5BigIpAdapter,
    F5BigIpDriver,
)
from .aruba_cx import ArubaCXAdapter, ArubaCXDriver
from .cisco_wlc import CiscoWlcAdapter, CiscoWlcDriver
from .fortios import FortiOSAdapter, FortiOSDriver
from .frr import FRRoutingAdapter, FRRoutingDriver
from .ios_xe import CiscoIOSXEAdapter, CiscoIOSXEDriver
from .eos import AristaEOSAdapter, AristaEOSDriver
from .junos import JunosAdapter, JunosDriver
from .nxos import CiscoNXOSAdapter, CiscoNXOSDriver
from .panos import PanOsAdapter, PanOsDriver
from .ios import CiscoIOSDriver

__all__ = [
    "AtlasLabFirewallAdapter",
    "AtlasLabFirewallDriver",
    "AtlasLabSwitchAdapter",
    "AtlasLabSwitchDriver",
    "A10AcosAdapter",
    "A10AcosDriver",
    "CitrixAdcAdapter",
    "CitrixAdcDriver",
    "F5BigIpAdapter",
    "F5BigIpDriver",
    "ArubaCXAdapter",
    "ArubaCXDriver",
    "CiscoWlcAdapter",
    "CiscoWlcDriver",
    "CiscoIOSDriver",
    "FortiOSAdapter",
    "FortiOSDriver",
    "PanOsAdapter",
    "PanOsDriver",
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
