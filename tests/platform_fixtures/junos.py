"""Sanitized Junos transcripts (EX4300, 21.4R3 shapes)."""

SHOW_VERSION = """\
Hostname: edge-jnp1
Model: ex4300-24t
Junos: 21.4R3.15
JUNOS OS Kernel 64-bit  [20220607.7c2e161_builder_stable_12_214]
JUNOS OS libs [20220607.7c2e161_builder_stable_12_214]
JUNOS EX  Software Suite [21.4R3.15]
"""

SHOW_CHASSIS = """\
Hardware inventory:
Item             Version  Part number  Serial number     Description
Chassis                                JN24LAB0004       EX4300-24T
Pseudo CB 0
Routing Engine 0          BUILTIN      BUILTIN           EX4300-24T
FPC 0            REV 12   611-063977   JN24LAB0004       EX4300-24T
  PIC 0                   BUILTIN      BUILTIN           24x 10/100/1000 Base-T
Power Supply 0   REV 03   740-046873   1EDL24700AA       JPSU-350-AC-AFO
Fan Tray 0                                               Fan Module, Airflow Out (AFO)
"""

SHOW_INT_TERSE = """\
Interface               Admin Link Proto    Local                 Remote
ge-0/0/0                up    up
ge-0/0/0.0              up    up   inet     10.10.40.1/31
ge-0/0/1                up    down
xe-0/0/1                up    up
xe-0/0/1.0              up    up   inet     10.10.41.0/31
lo0                     up    up
lo0.0                   up    up   inet     192.0.2.14/32
me0                     up    up
me0.0                   up    up   inet     10.10.20.4/24
irb                     up    up
irb.10                  up    up   inet     10.10.10.5/24
"""

SHOW_LLDP = """\
Local Interface    Parent Interface    Chassis Id          Port info          System Name
ge-0/0/0           -                   28:99:3a:ab:00:01   Ethernet2          leaf-eos1
xe-0/0/1           -                   00:aa:bb:01:00:01   Gi1/0/2            core-sw1
me0                -                   44:f4:77:aa:00:99   ge-0/0/12          mgmt-sw
"""

SHOW_ROUTES = """\
inet.0: 12 destinations, 12 routes (12 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

0.0.0.0/0          *[Static/5] 12w3d 02:11:04
                    >  to 10.10.20.1 via me0.0
10.10.40.0/31      *[Direct/0] 12w3d 02:11:04
                    >  via ge-0/0/0.0
192.0.2.13/32      *[OSPF/10] 10w1d 11:22:33, metric 2
                    >  to 10.10.40.0 via ge-0/0/0.0

mgmt_junos.inet.0: 2 destinations, 2 routes (2 active, 0 holddown, 0 hidden)
"""

SHOW_BGP = """\
Groups: 1 Peers: 1 Down peers: 0
Table          Tot Paths  Act Paths Suppressed    History Damp State    Pending
inet.0
                      18         18          0          0          0          0
Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State|#Active/Received/Accepted/Damped...
10.10.40.0            65020     204811     204799       0       0    12w3d 2:11:01 Establ
  inet.0: 18/18/18/0
"""

SHOW_OSPF = """\
Address          Interface              State           ID               Pri  Dead
10.10.40.0       ge-0/0/0.0             Full            192.0.2.13       128    35
"""

SHOW_CONFIG_SET = """\
set version 21.4R3.15
set system host-name edge-jnp1
set system name-server 192.0.2.53
set system ntp server 192.0.2.250
set interfaces ge-0/0/0 unit 0 family inet address 10.10.40.1/31
set interfaces lo0 unit 0 family inet address 192.0.2.14/32
set interfaces me0 unit 0 family inet address 10.10.20.4/24
set routing-instances mgmt_junos description management
set protocols ospf area 0.0.0.0 interface ge-0/0/0.0
set protocols bgp group underlay neighbor 10.10.40.0 peer-as 65020
set protocols lldp interface all
"""

UNSUPPORTED = """\
           ^
unknown command.
"""


def normal() -> dict:
    return {
        "show version": SHOW_VERSION,
        "show chassis hardware": SHOW_CHASSIS,
        "show interfaces terse": SHOW_INT_TERSE,
        "show lldp neighbors": SHOW_LLDP,
        "show route": SHOW_ROUTES,
        "show bgp summary": SHOW_BGP,
        "show ospf neighbor": SHOW_OSPF,
        "show configuration | display set": SHOW_CONFIG_SET,
        "show route instance": "",
        "show ethernet-switching table": "",
    }
