"""Sanitized ArubaOS-CX transcripts (6300M, 10.11 shapes).

TRANSCRIPT VALIDATED fixtures with documentation addressing throughout.
"""

SHOW_VERSION = """\
-----------------------------------------------------
ArubaOS-CX
(c) Copyright 2017-2023 Hewlett Packard Enterprise Development LP
-----------------------------------------------------
Version      : FL.10.11.1021
Build Date   : 2023-05-26 12:57:16 PDT
Build ID     : ArubaOS-CX:FL.10.11.1021:1e0ee5334c73:202305261136
Build SHA    : 1e0ee5334c736d5ac1a2d312a2c53961c2f30c15
Active Image : primary

Service OS Version : FL.01.12.0002
BIOS Version       : FL.01.0002
"""

SHOW_SYSTEM = """\
Hostname                : hyd-agg-01
System Description      : FL.10.11.1021
System Contact          :
System Location         : hyderabad-dc-row2
Vendor                  : Aruba
Product Name            : JL662A 6300M 24G 4SFP56 Swch
Chassis Serial Nbr      : SG12KW1234
Base MAC Address        : 88:3a:30:aa:bb:00
ArubaOS-CX Version      : FL.10.11.1021
Time Zone               : UTC

Up Time                 : 41 days, 3 hours, 20 minutes
CPU Util (%)            : 6
Memory Usage (%)        : 21
"""

SHOW_IP_INTERFACE_BRIEF = """\
Interface       IP Address        Interface Status
                                  link/admin
--------------- ----------------- ---------------
vlan10          172.20.60.1/24    up/up
vlan20          172.20.61.1/24    up/up
loopback0       10.255.0.60/32    up/up
1/1/24          172.20.20.60/24   up/up
"""

SHOW_INTERFACE_BRIEF = """\
--------------------------------------------------------------------------------
Port       Native  Mode   Type      Enabled Status  Reason                 Speed
           VLAN                                                            (Mb/s)
--------------------------------------------------------------------------------
1/1/1      10      access 1GbT      yes     up                             1000
1/1/2      20      access 1GbT      yes     up                             1000
1/1/3      1       access 1GbT      yes     down    Waiting for link       --
1/1/24     --      routed 1GbT      yes     up                             1000
lag1       10      trunk  --        yes     up                             2000
"""

SHOW_LLDP_NEIGHBORS = """\
LLDP Neighbor Information
=========================

Total Neighbor Entries          : 2
Total Neighbor Entries Deleted  : 0
Total Neighbor Entries Dropped  : 0
Total Neighbor Entries Aged-Out : 0

LOCAL-PORT  CHASSIS-ID         PORT-ID     PORT-DESC        TTL      SYS-NAME
--------------------------------------------------------------------------------
1/1/1       52:54:00:1a:2b:10  Gi0/1       GigabitEthernet  120      hyd-core-01
1/1/2       52:54:00:1a:2b:20  ge-0/0/5    ge-0/0/5         120      hyd-edge-02
"""

SHOW_VLAN = """\
--------------------------------------------------------------------------------------
VLAN  Name                              Status  Reason  Type      Interfaces
--------------------------------------------------------------------------------------
1     DEFAULT_VLAN_1                    up      ok      default   1/1/3
10    users                             up      ok      static    1/1/1,lag1
20    servers                           up      ok      static    1/1/2
"""

SHOW_LACP_AGGREGATES = """\
Aggregate name        : lag1
Interfaces            : 1/1/21 1/1/22
Heartbeat rate        : Slow
Aggregate mode        : Active
"""

SHOW_IP_ROUTE = """\
Displaying ipv4 routes selected for forwarding

'[x/y]' denotes [distance/metric]

0.0.0.0/0, vrf default
    via  172.20.20.1,  [1/0],  static
10.255.0.60/32, vrf default
    via  loopback0,  [0/0],  connected
172.20.60.0/24, vrf default
    via  vlan10,  [0/0],  connected
172.20.61.0/24, vrf default
    via  vlan20,  [0/0],  connected
192.0.2.128/25, vrf default
    via  172.20.60.3,  [110/2],  ospf
"""

SHOW_OSPF_NEIGHBORS = """\
VRF : default                          Process : 1
===================================================

Total Number of Neighbors : 1

Neighbor ID      Priority  State             Nbr Address       Interface
-------------------------------------------------------------------------
192.0.2.130      1         FULL/DR           172.20.60.3       vlan10
"""

SHOW_BGP_SUMMARY = """\
VRF : default
BGP Summary
-----------
 Local AS               : 65060        BGP Router Identifier  : 10.255.0.60
 Peers                  : 1            Log Neighbor Changes   : No
 Cfg. Hold Time         : 180          Cfg. Keep Alive        : 60
 Confederation Id       : 0

 Neighbor        Remote-AS MsgRcvd MsgSent   Up/Down Time State        AdminStatus
 172.20.60.2     65010       12842   12836   29d:14h:06m  Established  Up
"""

SHOW_RUNNING_CONFIG = """\
!Version ArubaOS-CX FL.10.11.1021
hostname hyd-agg-01
vlan 10
    name users
vlan 20
    name servers
interface 1/1/24
    no shutdown
    ip address 172.20.20.60/24
"""

UNKNOWN = "% Unknown command."


def normal() -> dict:
    return {
        "show version": SHOW_VERSION,
        "show system": SHOW_SYSTEM,
        "show ip interface brief": SHOW_IP_INTERFACE_BRIEF,
        "show interface brief": SHOW_INTERFACE_BRIEF,
        "show lldp neighbor-info": SHOW_LLDP_NEIGHBORS,
        "show vlan": SHOW_VLAN,
        "show lacp aggregates": SHOW_LACP_AGGREGATES,
        "show ip route": SHOW_IP_ROUTE,
        "show ip ospf neighbors": SHOW_OSPF_NEIGHBORS,
        "show bgp ipv4 unicast summary": SHOW_BGP_SUMMARY,
        "show running-config": SHOW_RUNNING_CONFIG,
    }
