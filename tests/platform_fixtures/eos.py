"""Sanitized Arista EOS transcripts (7050X, 4.30.5M shapes). CLI text only —
eAPI is deliberately not required (Part 9)."""

SHOW_VERSION = """\
Arista DCS-7050SX3-48YC8-R
Hardware version: 11.02
Serial number: JPE24LAB003
Hardware MAC address: 2899.3aab.0001
System MAC address: 2899.3aab.0001

Software image version: 4.30.5M
Architecture: x86_64
Internal build version: 4.30.5M-33796583.4305M
Internal build ID: 4f80e1e7-a51e-4b0f-a9e5-lab000000000
Image format version: 3.0
Image optimization: Sand-4GB

Uptime: 12 weeks, 3 days, 2 hours and 41 minutes
Total memory: 8098984 kB
Free memory: 5183660 kB
"""

SHOW_HOSTNAME = """\
Hostname: leaf-eos1
FQDN:     leaf-eos1.lab.example
"""

SHOW_IP_INT_BRIEF = """\
                                                                                Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ---------- -------
Ethernet1         10.10.30.1/31         up           up                 9214
Loopback0         192.0.2.13/32         up           up                65535
Management1       10.10.20.3/24         up           up                 1500
Vlan10            10.10.10.4/24         up           up                 9214
"""

SHOW_LLDP = """\
Last table change time   : 0:05:31 ago
Number of table inserts  : 4
Number of table deletes  : 0
Number of table drops    : 0
Number of table age-outs : 0

Port          Neighbor Device ID             Neighbor Port ID           TTL
---------- ------------------------------ ---------------------- ---
Et1           core-sw1                       Gi1/0/1                    120
Et49/1        dist-nxos1                     Ethernet1/1                120
Ma1           mgmt-sw                        ge-0/0/12                  120
"""

SHOW_MLAG = """\
MLAG Configuration:
domain-id                          :              mlag-pod1
local-interface                    :                 Vlan4094
peer-address                       :              10.255.255.2
peer-link                          :             Port-Channel10
peer-config                        :               consistent

MLAG Status:
state                              :                   Active
negotiation status                 :                Connected
peer-link status                   :                       Up
local-int status                   :                       Up
system-id                          :        28:99:3a:ab:00:01
dual-primary detection             :                 Disabled

MLAG Ports:
Disabled                           :                        0
Configured                         :                        0
Inactive                           :                        0
Active-partial                     :                        0
Active-full                        :                        2
"""

SHOW_ROUTES = """\
VRF: default
Codes: C - connected, S - static, K - kernel,
       O - OSPF, IA - OSPF inter area, B - BGP

Gateway of last resort:
 S        0.0.0.0/0 [1/0] via 10.10.20.1, Management1

 C        10.10.10.0/24 is directly connected, Vlan10
 C        10.10.30.0/31 is directly connected, Ethernet1
 B E      192.0.2.11/32 [200/0] via 10.10.30.0, Ethernet1
"""

SHOW_BGP = """\
BGP summary information for VRF default
Router identifier 192.0.2.13, local AS number 65020
Neighbor Status Codes: m - Under maintenance
  Neighbor  V AS      MsgRcvd MsgSent InQ OutQ Up/Down  State    PfxRcd PfxAcc
  10.10.30.0 4 65010   120031  120017   0    0   12w3d  Estab    18     18
"""

SHOW_OSPF = """\
Neighbor ID     Instance VRF      Pri State                  Dead Time   Address         Interface
192.0.2.11      1        default  1   FULL                   00:00:33    10.10.30.0      Ethernet1
"""

SHOW_VLAN = """\
VLAN  Name                             Status    Ports
----- -------------------------------- --------- -------------------------------
1     default                          active    Et2
10    USERS                            active    Cpu, Et1, Po10
4094  MLAG_PEER                        active    Cpu, Po10
"""

SHOW_VRF = """\
   VRF            Protocols       State         Interfaces
-------------- --------------- ---------------- ----------
   default        IPv4,IPv6     v4:routing,      Et1, Lo0,
                                v6:no routing    Vl10
   MGMT           IPv4,IPv6     v4:no routing,   Ma1
                                v6:no routing
"""

SHOW_RUNNING = """\
! Command: show running-config
! device: leaf-eos1 (DCS-7050SX3-48YC8-R, EOS-4.30.5M)
!
hostname leaf-eos1
!
ntp server 192.0.2.250
!
interface Ethernet1
   description to-core-sw1
   no switchport
   ip address 10.10.30.1/31
!
interface Loopback0
   ip address 192.0.2.13/32
!
router bgp 65020
   router-id 192.0.2.13
   neighbor 10.10.30.0 remote-as 65010
!
end
"""

UNSUPPORTED = "% Invalid input"
MLAG_DISABLED = "MLAG is disabled"


def normal() -> dict:
    return {
        "show version": SHOW_VERSION,
        "show hostname": SHOW_HOSTNAME,
        "show ip interface brief": SHOW_IP_INT_BRIEF,
        "show lldp neighbors": SHOW_LLDP,
        "show mlag": SHOW_MLAG,
        "show ip route vrf all": SHOW_ROUTES,
        "show ip bgp summary vrf all": SHOW_BGP,
        "show ip ospf neighbor": SHOW_OSPF,
        "show vlan": SHOW_VLAN,
        "show vrf": SHOW_VRF,
        "show running-config": SHOW_RUNNING,
        "show mac address-table": "",
        "show inventory": "",
    }
