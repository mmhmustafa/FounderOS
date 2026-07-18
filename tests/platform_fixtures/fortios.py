"""Sanitized FortiOS transcripts (FortiGate-100F, v7.2.5 shapes).

TRANSCRIPT VALIDATED fixtures: realistic FortiOS 7.2 output with every
address, serial and hostname replaced by lab/documentation values. No
secret material (no psksecret, no passwords) appears here by design.
"""

GET_SYSTEM_STATUS = """\
Version: FortiGate-100F v7.2.5,build1517,230608 (GA.F)
Security Level: 1
Firmware Signature: certified
Virus-DB: 91.08880(2023-06-07 18:07)
Extended DB: 91.08880(2023-06-07 18:07)
AV AI/ML Model: 2.14030(2023-06-08 01:23)
IPS-DB: 22.00476(2023-06-07 23:35)
Serial-Number: FG100F1234567890
BIOS version: 05000000
System Part-Number: P24522-04
Log hard disk: Available
Hostname: hyd-fw-01
Operation Mode: NAT
Current virtual domain: root
Max number of virtual domains: 10
Virtual domains status: 2 in NAT mode, 0 in TP mode
Virtual domain configuration: multiple
FIPS-CC mode: disable
Current HA mode: a-p, master
System time: Mon Jul 14 06:59:32 2026
"""

GET_SYSTEM_INTERFACE = """\
== [ port1 ]
        name: port1   mode: static    ip: 172.20.20.34 255.255.255.0   status: up   netbios-forward: disable    type: physical   netflow-sampler: disable    sflow-sampler: disable    src-check: enable    explicit-web-proxy: disable    explicit-ftp-proxy: disable    proxy-captive-portal: disable    mtu-override: disable    wccp: disable    drop-overlapped-fragment: disable
== [ port2 ]
        name: port2   mode: static    ip: 203.0.113.2 255.255.255.0   status: up   netbios-forward: disable    type: physical
== [ port3 ]
        name: port3   mode: static    ip: 172.20.30.1 255.255.255.0   status: up   netbios-forward: disable    type: physical
== [ port4 ]
        name: port4   mode: dhcp      ip: 0.0.0.0 0.0.0.0   status: down   netbios-forward: disable    type: physical
== [ mgmt ]
        name: mgmt    mode: static    ip: 10.10.20.34 255.255.255.0   status: up   type: physical
"""

SHOW_ZONE = """\
config system zone
    edit "trust"
        set interface "port1" "port3"
    next
    edit "untrust"
        set interface "port2"
    next
    edit "mgmt-zone"
        set intrazone allow
        set interface "mgmt"
    next
end
"""

SHOW_POLICY = """\
config firewall policy
    edit 1
        set name "trust-to-internet"
        set uuid 1a2b3c4d-0000-0000-0000-000000000001
        set srcintf "port1"
        set dstintf "port2"
        set srcaddr "all"
        set dstaddr "all"
        set action accept
        set schedule "always"
        set service "HTTPS" "DNS" "HTTP"
        set logtraffic all
        set nat enable
    next
    edit 2
        set name "dmz-web"
        set srcintf "untrust"
        set dstintf "trust"
        set srcaddr "all"
        set dstaddr "web-server-vip"
        set action accept
        set schedule "always"
        set service "HTTPS"
        set logtraffic all
    next
    edit 3
        set name "block-guest"
        set srcintf "port3"
        set dstintf "port1"
        set srcaddr "guest-net"
        set dstaddr "internal-net"
        set action deny
        set schedule "always"
        set service "ALL"
        set status disable
    next
    edit 4
        set name "implicit-deny"
        set srcintf "any"
        set dstintf "any"
        set srcaddr "all"
        set dstaddr "all"
        set action deny
        set schedule "always"
        set service "ALL"
        set logtraffic all
    next
end
"""

SHOW_VIP = """\
config firewall vip
    edit "web-server-vip"
        set uuid 2b3c4d5e-0000-0000-0000-000000000010
        set extip 203.0.113.80
        set mappedip "172.20.20.80"
        set extintf "port2"
        set portforward enable
        set extport 443
        set mappedport 443
    next
end
"""

GET_VPN = """\
'to-branch' 198.51.100.1:0  selectors 1  rx 1048576  tx 524288
'to-dc'     203.0.113.9:0    selectors 0  rx 0  tx 0
"""

GET_HA = """\
HA Health Status: OK
Model: FortiGate-100F
Mode: HA A-P
Group Name: hyd-cluster
Group ID: 1
Debug: 0
Cluster Uptime: 40 days 02:11:04
Cluster state change time: 2026-06-04 04:48:00
Master selected using:
    <2026/06/04 04:48:00> FG100F1234567890 is selected as the master because it has the largest value of override priority.
Primary  : hyd-fw-01       , FG100F1234567890, HA cluster index = 0
Secondary: hyd-fw-02       , FG100F0987654321, HA cluster index = 1
number of vcluster: 1
"""

# NOTE: the HA member lines in real 7.2 output read "Master :" / "Slave :" on
# many builds; this fixture uses that older shape to exercise the parser.
GET_HA_MASTER_SLAVE = """\
HA Health Status: OK
Model: FortiGate-100F
Mode: HA A-P
Group Name: hyd-cluster
Master : hyd-fw-01       , FG100F1234567890, HA cluster index = 0
Slave  : hyd-fw-02       , FG100F0987654321, HA cluster index = 1
"""

SHOW_VDOM = """\
config vdom
    edit root
    next
    edit dmz
    next
end
"""

GET_ROUTES = """\
Routing table for VRF=0
S*      0.0.0.0/0 [10/0] via 203.0.113.1, port2, 00:00:01
C       172.20.20.0/24 is directly connected, port1
C       172.20.30.0/24 is directly connected, port3
C       203.0.113.0/24 is directly connected, port2
B       10.1.0.0/16 [20/0] via 198.51.100.2, port2, 01:02:03
O       10.2.0.0/16 [110/20] via 172.20.30.2, port3, 00:30:00
"""

SHOW_STATIC = """\
config router static
    edit 1
        set gateway 203.0.113.1
        set device "port2"
    next
end
"""

GET_BGP = """\
BGP router identifier 10.255.0.34, local AS number 65100
BGP table version is 42
3 BGP AS-PATH entries
0 BGP community entries

Neighbor        V    AS  MsgRcvd  MsgSent  TblVer  InQ  OutQ  Up/Down   State/PfxRcd
198.51.100.2    4  65200     1024      512      42    0     0  1d02h05m           12
203.0.113.9     4  65300      256      256      42    0     0  00:00:42            0

Total number of neighbors 2
"""

GET_OSPF = """\
OSPF process 0, VRF default:
Neighbor ID     Pri   State           Dead Time   Address         Interface
10.255.0.2        1   Full/DR         00:00:38    172.20.30.2     port3
"""

SHOW = """\
config system global
    set admin-sport 443
    set hostname "hyd-fw-01"
    set timezone 04
end
config system interface
    edit "port1"
        set ip 172.20.20.34 255.255.255.0
        set allowaccess ping https ssh
    next
end
config firewall policy
    edit 1
        set name "trust-to-internet"
        set action accept
    next
end
"""

# Fortinet rejects an unknown command with this phrasing.
UNKNOWN = "Command fail. Return code -61"


def normal() -> dict:
    """A healthy FortiGate with two VDOMs, HA, VPNs and OSPF+BGP,
    keyed by the exact commands the driver issues."""

    return {
        "get system status": GET_SYSTEM_STATUS,
        "get system interface": GET_SYSTEM_INTERFACE,
        "show system zone": SHOW_ZONE,
        "show firewall policy": SHOW_POLICY,
        "show firewall vip": SHOW_VIP,
        "get vpn ipsec tunnel summary": GET_VPN,
        "get system ha status": GET_HA_MASTER_SLAVE,
        "show vdom": SHOW_VDOM,
        "get router info routing-table all": GET_ROUTES,
        "show router static": SHOW_STATIC,
        "get router info bgp summary": GET_BGP,
        "get router info ospf neighbor": GET_OSPF,
        "show": SHOW,
    }
