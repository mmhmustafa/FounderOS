"""Sanitized IOS-XE transcripts (Catalyst 9300, 17.09.04a shapes)."""

SHOW_VERSION = """\
Cisco IOS XE Software, Version 17.09.04a
Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_IOSXE), Version 17.9.4a, RELEASE SOFTWARE (fc3)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2023 by Cisco Systems, Inc.

core-sw1 uptime is 12 weeks, 3 days, 4 hours, 12 minutes
Uptime for this control processor is 12 weeks, 3 days, 4 hours, 14 minutes
System returned to ROM by Reload Command

cisco C9300-24T (X86) processor with 1338934K/6147K bytes of memory.
Processor board ID FOC24LAB001
8 Gigabit Ethernet interfaces
2048K bytes of non-volatile configuration memory.

Configuration register is 0x102
"""

SHOW_INVENTORY = """\
NAME: "c93xx Stack", DESCR: "c93xx Stack"
PID: C9300-24T        , VID: V03  , SN: FOC24LAB001

NAME: "Switch 1", DESCR: "C9300-24T"
PID: C9300-24T        , VID: V03  , SN: FOC24LAB001

NAME: "Switch 1 - Power Supply A", DESCR: "Switch 1 - Power Supply A"
PID: PWR-C1-350WAC-P  , VID: V02  , SN: LIT24LAB77A
"""

SHOW_IP_INT_BRIEF = """\
Interface              IP-Address      OK? Method Status                Protocol
Vlan1                  unassigned      YES NVRAM  administratively down down
Vlan10                 10.10.10.2      YES NVRAM  up                    up
GigabitEthernet1/0/1   unassigned      YES unset  up                    up
GigabitEthernet1/0/2   unassigned      YES unset  up                    up
GigabitEthernet1/0/24  unassigned      YES unset  down                  down
Loopback0              192.0.2.11      YES NVRAM  up                    up
Port-channel1          10.10.99.2      YES NVRAM  up                    up
"""

SHOW_LLDP_DETAIL = """\
------------------------------------------------
Local Intf: Gi1/0/1
Chassis id: 00aa.bb01.0001
Port id: Ethernet1
Port Description: to-core-sw1
System Name: leaf-eos1.lab.example

System Description:
Arista Networks EOS version 4.30.5M

Time remaining: 96 seconds
System Capabilities: B,R
Enabled Capabilities: B,R
Management Addresses:
    IP: 10.10.20.3
Auto Negotiation - supported, enabled

------------------------------------------------
Local Intf: Gi1/0/2
Chassis id: 00bb.cc02.0002
Port id: xe-0/0/1
Port Description: uplink
System Name: edge-jnp1

System Description:
Juniper Networks, Inc. ex4300-24t Ethernet Switch, kernel JUNOS 21.4R3.15

Time remaining: 102 seconds
System Capabilities: B,R
Enabled Capabilities: B,R
Management Addresses:
    IP: 10.10.20.4

Total entries displayed: 2
"""

SHOW_CDP_DETAIL = """\
-------------------------
Device ID: dist-nxos1(FDO24LAB002)
Entry address(es):
  IP address: 10.10.20.2
Platform: N9K-C93180YC-EX, Capabilities: Router Switch CVTA phone port
Interface: GigabitEthernet1/0/3,  Port ID (outgoing port): Ethernet1/49
Holdtime : 133 sec

Version :
Cisco Nexus Operating System (NX-OS) Software, Version 10.2(5)

advertisement version: 2
Duplex: full

Total cdp entries displayed : 1
"""

SHOW_IP_ROUTE = """\
Codes: L - local, C - connected, S - static, R - RIP, M - mobile, B - BGP
       D - EIGRP, EX - EIGRP external, O - OSPF, IA - OSPF inter area

Gateway of last resort is 10.10.99.1 to network 0.0.0.0

S*    0.0.0.0/0 [1/0] via 10.10.99.1
      10.0.0.0/8 is variably subnetted, 4 subnets, 2 masks
C        10.10.10.0/24 is directly connected, Vlan10
L        10.10.10.2/32 is directly connected, Vlan10
C        10.10.99.0/30 is directly connected, Port-channel1
L        10.10.99.2/32 is directly connected, Port-channel1
O     192.0.2.12/32 [110/2] via 10.10.99.1, 2w3d, Port-channel1
"""

SHOW_BGP_SUMMARY = """\
BGP router identifier 192.0.2.11, local AS number 65010
BGP table version is 44, main routing table version 44

Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.10.99.1      4        65000  120441  120440       44    0    0 2w3d            12
"""

SHOW_OSPF_NEIGHBOR = """\
Neighbor ID     Pri   State           Dead Time   Address         Interface
192.0.2.12        1   FULL/DR         00:00:36    10.10.99.1      Port-channel1
"""

SHOW_VLAN_BRIEF = """\
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi1/0/24
10   USERS                            active    Gi1/0/1, Gi1/0/2
99   TRANSIT                          active
"""

SHOW_ETHERCHANNEL = """\
Flags:  D - down        P - bundled in port-channel
        U - in use      f - failed to allocate aggregator

Number of channel-groups in use: 1
Number of aggregators:           1

Group  Port-channel  Protocol    Ports
------+-------------+-----------+-----------------------------------------------
1      Po1(RU)         LACP      Gi1/0/23(P) Gi1/0/24(P)
"""

SHOW_RUNNING = """\
Building configuration...

Current configuration : 4183 bytes
!
version 17.9
hostname core-sw1
!
ntp server 192.0.2.250
logging host 192.0.2.251
!
interface Loopback0
 ip address 192.0.2.11 255.255.255.255
!
interface Vlan10
 ip address 10.10.10.2 255.255.255.0
!
router ospf 1
 router-id 192.0.2.11
!
router bgp 65010
 bgp router-id 192.0.2.11
 neighbor 10.10.99.1 remote-as 65000
!
end
"""

UNSUPPORTED = "% Invalid input detected at '^' marker."
PRIVILEGE_DENIED = "% Authorization failed."
EMPTY = ""

# A degraded variant: LLDP disabled, no BGP configured.
SHOW_LLDP_DISABLED = "% LLDP is not enabled"
SHOW_BGP_NOT_RUNNING = ""


def normal() -> dict:
    return {
        "show version": SHOW_VERSION,
        "show inventory": SHOW_INVENTORY,
        "show ip interface brief": SHOW_IP_INT_BRIEF,
        "show lldp neighbors detail": SHOW_LLDP_DETAIL,
        "show cdp neighbors detail": SHOW_CDP_DETAIL,
        "show ip route": SHOW_IP_ROUTE,
        "show ip bgp summary": SHOW_BGP_SUMMARY,
        "show ip ospf neighbor": SHOW_OSPF_NEIGHBOR,
        "show vlan brief": SHOW_VLAN_BRIEF,
        "show etherchannel summary": SHOW_ETHERCHANNEL,
        "show running-config": SHOW_RUNNING,
        "show interfaces": "GigabitEthernet1/0/1 is up, line protocol is up\n",
        "show mac address-table": EMPTY,
        "show spanning-tree": EMPTY,
        "show standby brief": EMPTY,
    }
