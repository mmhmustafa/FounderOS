"""Sanitized PAN-OS transcripts (PA-850, 10.2 shapes).

TRANSCRIPT VALIDATED fixtures: realistic PAN-OS 10.2 op-command output
with every address, serial and hostname replaced by lab/documentation
values. No secret material (no keys, no certificates, no passwords)
appears here by design.
"""

SHOW_SYSTEM_INFO = """\
hostname: sec-fw-01
ip-address: 172.20.20.42
public-ip-address: unknown
netmask: 255.255.255.0
default-gateway: 172.20.20.1
mac-address: 00:1b:17:00:01:10
time: Mon Jul 14 06:59:40 2026
uptime: 41 days, 3:12:09
family: 800
model: PA-850
serial: 013201001234
sw-version: 10.2.4-h2
app-version: 8730-8055
threat-version: 8730-8055
device-dictionary-version: 105-458
url-filtering-version: 20260713.20012
logdb-version: 10.2.0
multi-vsys: on
operational-mode: normal
device-certificate-status: Valid
"""

SHOW_INTERFACE_ALL = """\
total configured hardware interfaces: 5

name                    id    speed/duplex/state        mac address
--------------------------------------------------------------------------------
ethernet1/1             16    1000/full/up              00:1b:17:00:01:11
ethernet1/2             17    1000/full/up              00:1b:17:00:01:12
ethernet1/3             18    1000/full/up              00:1b:17:00:01:13
ethernet1/4             19    ukn/ukn/down              00:1b:17:00:01:14
mgmt                    0     1000/full/up              00:1b:17:00:01:10

aggregation groups: 0

total configured logical interfaces: 5

name                id    vsys zone             forwarding               tag    address
------------------- ----- ---- ---------------- ------------------------ ------ ------------------
ethernet1/1         16    1    untrust          vr:default               0      203.0.113.42/24
ethernet1/2         17    1    trust            vr:default               0      172.20.40.1/24
ethernet1/3         18    2    dmz              vr:tenant-b              0      172.20.50.1/24
ethernet1/4         19    1                     vr:default               0      N/A
mgmt                0     0                     N/A                      0      172.20.20.42/24
"""

SHOW_SECURITY_POLICY = """\
vsys1 {
  rule1 {
    from trust;
    source any;
    source-region none;
    to untrust;
    destination any;
    destination-region none;
    user any;
    category any;
    application/service [ web-browsing/tcp/any/80 ssl/tcp/any/443 ];
    action allow;
    icmp-unreachable: no
    terminal yes;
  }

  block-dmz-to-trust {
    from dmz;
    source any;
    to trust;
    destination any;
    user any;
    category any;
    application/service any/any/any/any;
    action deny;
    icmp-unreachable: no
    terminal yes;
  }

  cleanup-deny {
    from any;
    source any;
    to any;
    destination any;
    user any;
    category any;
    application/service any/any/any/any;
    action deny;
    icmp-unreachable: no
    terminal yes;
  }
}
"""

SHOW_NAT_POLICY = """\
vsys1 {
  outbound-pat {
    translate-to "src: ethernet1/1 203.0.113.42 (dynamic-ip-and-port) (pool idx: 1)";
    terminal no;
    from trust;
    source any;
    to untrust;
    destination any;
    service any/any/any;
  }

  web-dnat {
    translate-to "dst: 172.20.40.10";
    terminal no;
    from untrust;
    source any;
    to untrust;
    destination 203.0.113.80;
    service tcp/any/80;
  }
}
"""

SHOW_VPN_IPSEC_SA = """\
GwID/client IP  TnID   Peer-Address           Tunnel(Gateway)                              Algorithm          SPI(in)  SPI(out) life(Sec/KB)
--------------  ----   ------------           ---------------                              ---------          -------  -------- ------------
1               1      198.51.100.9           to-branch(to-branch-gw)                      ESP/A128/SHA256    c94d2f01 01a3b9d2 2790/0
2               2      198.51.100.33          to-dr-site(to-dr-gw)                         ESP/A256/SHA384    83aa10fe 5cd41e07 3105/0

Total 2 tunnels found. 2 ipsec sa found.
"""

SHOW_HA_STATE = """\
Group 1:
  Mode: Active-Passive
  Local Information:
    Version: 1
    State: active (last 41 days)
    Device Information:
      Management IPv4 Address: 172.20.20.42/24
    Priority: 100
    Preemptive: no
  Peer Information:
    State: passive (last 41 days)
    Device Information:
      Management IPv4 Address: 172.20.20.43/24
      Serial Number: 013201005678
    Priority: 110
  Configuration Synchronization:
    Enabled: yes
    Running Configuration: synchronized
"""

SHOW_ROUTING_ROUTE = """\
flags: A:active, ?:loose, C:connect, H:host, S:static, ~:internal, R:rip, O:ospf, B:bgp,
       Oi:ospf intra-area, Oo:ospf inter-area, O1:ospf ext-type-1, O2:ospf ext-type-2, E:ecmp, M:multicast

VIRTUAL ROUTER: default (id 1)
  ==========
destination                                 nexthop                                 metric flags      age   interface          next-AS
0.0.0.0/0                                   203.0.113.1                             10     A S              ethernet1/1
172.20.40.0/24                              172.20.40.1                             0      A C              ethernet1/2
203.0.113.0/24                              203.0.113.42                            0      A C              ethernet1/1
10.255.0.0/24                               172.20.40.2                             30     A B        2d    ethernet1/2
192.0.2.128/25                              172.20.40.3                             110    A Oi       5d    ethernet1/2

VIRTUAL ROUTER: tenant-b (id 2)
  ==========
destination                                 nexthop                                 metric flags      age   interface          next-AS
172.20.50.0/24                              172.20.50.1                             0      A C              ethernet1/3

total routes shown: 6
"""

SHOW_BGP_PEER = """\
Peer: dc-core (id 1)
    virtual router: default
    Peer router id: 10.255.0.10
    Remote AS: 65010
    Peer group: datacenter (id 1)
    Peer status: Established, for 351042 seconds
    Peer address: 172.20.40.2:179
    Local address: 172.20.40.1:43521
    Prefix counter for send/receive: 12/48

Peer: branch-rtr (id 2)
    virtual router: default
    Peer router id: 10.255.0.30
    Remote AS: 65030
    Peer group: branches (id 2)
    Peer status: Active
    Peer address: 172.20.40.9:179
    Local address: 172.20.40.1:0
    Prefix counter for send/receive: 0/0
"""

SHOW_OSPF_NEIGHBOR = """\
Options: 0x80:reserved, O:Opaq-LSA capability, DC:demand circuits, EA:Ext-Attr LSA capability,
         N/P:NSSA option, MC:multicast, E:AS external LSA capability, T:TOS capability

virtual router: default
  neighbor address:  172.20.40.3
  local address binding: 172.20.40.1
  type:              dynamic
  status:            full
  neighbor router ID: 192.0.2.130
  area id:           0.0.0.0
  neighbor priority: 1
  lifetime remain:   38
  messages pending:  0
  LSA request pending: 0
  options:           0x42: O E
  hello suppressed:  no
"""

SHOW_LLDP_NEIGHBORS = """\
Port Name: ethernet1/2
Neighbor Details:
* Chassis Type: MAC address
  Chassis ID: 52:54:00:1a:2b:3c
* Port Description: GigabitEthernet0/1
* System Name: dc-core-sw1
* System Description: Cisco IOS Software
"""

SHOW_CONFIG_RUNNING = """\
deviceconfig {
  system {
    hostname sec-fw-01;
    ip-address 172.20.20.42;
  }
}
vsys {
  vsys1 {
    zone {
      trust;
      untrust;
    }
  }
}
"""

# PAN-OS rejects an unknown op command with this phrasing.
UNKNOWN = "Unknown command: garbage\n\nInvalid syntax."


def normal() -> dict:
    """A healthy multi-vsys PA-850 in an active-passive HA pair, keyed by
    the exact commands the driver issues."""

    return {
        "show system info": SHOW_SYSTEM_INFO,
        "show interface all": SHOW_INTERFACE_ALL,
        "show running security-policy": SHOW_SECURITY_POLICY,
        "show running nat-policy": SHOW_NAT_POLICY,
        "show vpn ipsec-sa": SHOW_VPN_IPSEC_SA,
        "show high-availability state": SHOW_HA_STATE,
        "show routing route": SHOW_ROUTING_ROUTE,
        "show routing protocol bgp peer": SHOW_BGP_PEER,
        "show routing protocol ospf neighbor": SHOW_OSPF_NEIGHBOR,
        "show lldp neighbors all": SHOW_LLDP_NEIGHBORS,
        "show config running": SHOW_CONFIG_RUNNING,
    }
