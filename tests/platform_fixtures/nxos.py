"""Sanitized NX-OS transcripts (Nexus 9300, 10.2(5) shapes)."""

SHOW_VERSION = """\
Cisco Nexus Operating System (NX-OS) Software
TAC support: http://www.cisco.com/tac
Copyright (C) 2002-2023, Cisco and/or its affiliates.

Software
  BIOS: version 07.69
  NXOS: version 10.2(5)
  BIOS compile time:  04/07/2021
  NXOS image file is: bootflash:///nxos64-cs.10.2.5.M.bin

Hardware
  cisco Nexus9000 C93180YC-EX chassis
  Intel(R) Xeon(R) CPU D-1528 @ 1.90GHz with 24632480 kB of memory.
  Processor Board ID FDO24LAB002

  Device name: dist-nxos1
  bootflash:   53298520 kB

Kernel uptime is 84 day(s), 2 hour(s), 11 minute(s), 4 second(s)
"""

SHOW_INVENTORY = """\
NAME: "Chassis",  DESCR: "Nexus9000 C93180YC-EX chassis"
PID: N9K-C93180YC-EX      ,  VID: V02 ,  SN: FDO24LAB002

NAME: "Slot 1",  DESCR: "48x10/25G+6x40/100G Ethernet Module"
PID: N9K-C93180YC-EX      ,  VID: V02 ,  SN: FDO24LAB002
"""

SHOW_INT_BRIEF = """\
--------------------------------------------------------------------------------
Port   VRF          Status IP Address                              Speed    MTU
--------------------------------------------------------------------------------
mgmt0  management   up     10.10.20.2                              1000     1500

--------------------------------------------------------------------------------
Ethernet      VLAN    Type Mode   Status  Reason                Speed     Port
Interface                                                                 Ch #
--------------------------------------------------------------------------------
Eth1/1        1       eth  trunk  up      none                   25G(D)     10
Eth1/2        1       eth  trunk  up      none                   25G(D)     10
Eth1/49       --      eth  routed up      none                  100G(D)     --
Eth1/50       --      eth  routed down    Administratively down 100G(D)     --

--------------------------------------------------------------------------------
Port-channel VLAN    Type Mode   Status  Reason                 Speed   Protocol
Interface
--------------------------------------------------------------------------------
Po10         1       eth  trunk  up      none                    a-25G(D)  lacp

--------------------------------------------------------------------------------
Interface     Secondary VLAN(Type)                    Status Reason
--------------------------------------------------------------------------------
Lo0           --                                      up     none
Vlan10        --                                      up     none
"""

SHOW_IP_INT_VRF_ALL = """\
IP Interface Status for VRF "default"(1)
Lo0, Interface status: protocol-up/link-up/admin-up, iod: 4,
  IP address: 192.0.2.12, IP subnet: 192.0.2.12/32 route-preference: 0, tag: 0
Vlan10, Interface status: protocol-up/link-up/admin-up, iod: 5,
  IP address: 10.10.10.3, IP subnet: 10.10.10.0/24 route-preference: 0, tag: 0
Eth1/49, Interface status: protocol-up/link-up/admin-up, iod: 8,
  IP address: 10.10.99.1, IP subnet: 10.10.99.0/30 route-preference: 0, tag: 0

IP Interface Status for VRF "management"(2)
mgmt0, Interface status: protocol-up/link-up/admin-up, iod: 2,
  IP address: 10.10.20.2, IP subnet: 10.10.20.0/24 route-preference: 0, tag: 0
"""

SHOW_LLDP = """\
Capability codes:
  (R) Router, (B) Bridge, (T) Telephone, (C) DOCSIS Cable Device
Device ID            Local Intf      Hold-time  Capability  Port ID
core-sw1             Eth1/49         120        BR          Gi1/0/3
leaf-eos1            Eth1/1          120        BR          Ethernet49/1
Total entries displayed: 2
"""

SHOW_CDP = """\
----------------------------------------
Device ID:core-sw1.lab.example
System Name: core-sw1

Interface address(es):
    IPv4 Address: 10.10.20.5
Platform: cisco C9300-24T, Capabilities: Router Switch IGMP Filtering
Interface: Ethernet1/49, Port ID (outgoing port): GigabitEthernet1/0/3
Holdtime: 133 sec
"""

SHOW_VPC = """\
Legend:
                (*) - local vPC is down, forwarding via vPC peer-link

vPC domain id                     : 10
Peer status                       : peer adjacency formed ok
vPC keep-alive status             : peer is alive
vPC role                          : primary
Number of vPCs configured         : 2

vPC Peer-link status
---------------------------------------------------------------------
id    Port   Status Active vlans
--    ----   ------ -------------------------------------------------
1     Po1    up     1,10,99
"""

SHOW_PORT_CHANNEL = """\
Flags:  D - Down        P - Up in port-channel (members)
        I - Individual  H - Hot-standby (LACP only)
        s - Suspended   r - Module-removed
        S - Switched    R - Routed
        U - Up (port-channel)
--------------------------------------------------------------------------------
Group Port-       Type     Protocol  Member Ports
      Channel
--------------------------------------------------------------------------------
10    Po10(SU)    Eth      LACP      Eth1/1(P)    Eth1/2(P)
"""

SHOW_ROUTES = """\
IP Route Table for VRF "default"
'*' denotes best ucast next-hop
'**' denotes best mcast next-hop

10.10.10.0/24, ubest/mbest: 1/0, attached
    *via 10.10.10.3, Vlan10, [0/0], 12w3d, direct
192.0.2.11/32, ubest/mbest: 1/0
    *via 10.10.99.2, Eth1/49, [110/41], 12w3d, ospf-1, intra
"""

SHOW_BGP = """\
BGP summary information for VRF default, address family IPv4 Unicast
BGP router identifier 192.0.2.12, local AS number 65000
Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.10.99.2      4 65010  204512  204488       88    0    0    12w3d 24
"""

SHOW_OSPF = """\
 OSPF Process ID 1 VRF default
 Total number of neighbors: 1
 Neighbor ID     Pri State            Up Time  Address         Interface
 192.0.2.11        1 FULL/BDR         12w3d    10.10.99.2      Eth1/49
"""

SHOW_VLAN = """\
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Eth1/1, Eth1/2
10   USERS                            active    Po10
99   TRANSIT                          active
"""

SHOW_VRF = """\
VRF-Name                           VRF-ID State   Reason
default                                 1 Up      --
management                              2 Up      --
"""

SHOW_RUNNING = """\
!Command: show running-config
!Running configuration last done at: Wed Jul 16 03:00:11 2026
version 10.2(5) Bios:version 07.69
hostname dist-nxos1

feature ospf
feature bgp
feature lldp
feature vpc

vrf context management
  ip route 0.0.0.0/0 10.10.20.1

interface Vlan10
  ip address 10.10.10.3/24

interface loopback0
  ip address 192.0.2.12/32

router ospf 1
  router-id 192.0.2.12
router bgp 65000
  router-id 192.0.2.12
  neighbor 10.10.99.2
    remote-as 65010
"""

UNSUPPORTED = "% Invalid command at '^' marker."
FEATURE_DISABLED = ""


def normal() -> dict:
    return {
        "show version": SHOW_VERSION,
        "show inventory": SHOW_INVENTORY,
        "show interface brief": SHOW_INT_BRIEF,
        "show ip interface vrf all": SHOW_IP_INT_VRF_ALL,
        "show lldp neighbors": SHOW_LLDP,
        "show cdp neighbors detail": SHOW_CDP,
        "show vpc": SHOW_VPC,
        "show port-channel summary": SHOW_PORT_CHANNEL,
        "show ip route vrf all": SHOW_ROUTES,
        "show ip bgp summary vrf all": SHOW_BGP,
        "show ip ospf neighbors": SHOW_OSPF,
        "show vlan brief": SHOW_VLAN,
        "show vrf": SHOW_VRF,
        "show running-config": SHOW_RUNNING,
        "show mac address-table": "",
        "show spanning-tree": "",
        "show hsrp brief": UNSUPPORTED,   # feature hsrp not enabled
    }
