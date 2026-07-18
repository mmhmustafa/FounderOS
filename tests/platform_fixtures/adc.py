"""Sanitized ADC-family transcripts: F5 BIG-IP (tmsh), Citrix ADC (ns),
A10 ACOS. TRANSCRIPT VALIDATED fixtures, documentation addressing.
"""

# -- F5 BIG-IP (tmsh) ---------------------------------------------------------

F5_SHOW_SYS_VERSION = """\
Sys::Version
Main Package
  Product     BIG-IP
  Version     17.1.1.3
  Build       0.0.5
  Edition     Point Release 3
  Date        Wed Feb 21 04:00:07 PST 2026
"""

F5_SHOW_SYS_HARDWARE = """\
Sys::Hardware
Chassis Information
  Maximum MAC Count   1
  Registration Key    -

Hardware Version Information
  Name          i5800
  Type          base-board
  Model         BIG-IP i5800
  Parameters    --    --
  Versions
    Version 0.0
Platform
  Name           BIG-IP i5800
  BIOS Revision  F5 Platforms, Inc. C119 BIOS OBJ-0087-03 (build 3.leaf.0)
  Base MAC       00:94:a1:aa:bb:00
  Appliance Serial  f5-krtn-wxyz
System Information
  Type                  C119
  Chassis Serial        chs614881s
  Level 200/400 Part    200-0413-02
"""

F5_LIST_SYS_GLOBAL = """\
sys global-settings {
    hostname hyd-lb-01.corp.example
}
"""

F5_LIST_MGMT_IP = """\
sys management-ip 172.20.20.80/24 {
    description configured-statically
}
"""

F5_LIST_NET_SELF = """\
net self internal-self {
    address 172.20.70.2/24
    allow-service {
        default
    }
    traffic-group traffic-group-local-only
    vlan internal
}
net self external-self {
    address 203.0.113.80/24
    traffic-group traffic-group-1
    vlan external
}
"""

F5_SHOW_NET_INTERFACE = """\
-------------------------------------------------------------------
Net::Interface
Name   Status   Bits   Bits   Pkts   Pkts  Drops  Errs        Media
                  In    Out     In    Out
-------------------------------------------------------------------
1.1        up  1.2T  850.3G  1.1G  890.4M     0     0  10000SR-FD
1.2        up  912.5G  1.3T  950.2M  1.2G     0     0  10000SR-FD
1.3      down      0      0      0      0     0     0         none
mgmt       up  15.2G   9.1G  22.1M   18.3M    0     0    1000T-FD
"""

F5_SHOW_LTM_VIRTUAL = """\
---------------------------------------------------------------
Ltm::Virtual Server: vs-web-443
---------------------------------------------------------------
  Status
    Availability     : available
    State            : enabled
    Reason           : The virtual server is available
  Destination        : 203.0.113.85:443

---------------------------------------------------------------
Ltm::Virtual Server: vs-api-8443
---------------------------------------------------------------
  Status
    Availability     : offline
    State            : enabled
    Reason           : The children pool member(s) are down
  Destination        : 203.0.113.86:8443
"""

F5_SHOW_CM_DEVICE = """\
--------------------------------------------
CentMgmt::Device
Name                    hyd-lb-01.corp.example
Failover State          active
Management Ip           172.20.20.80
Configsync Ip           172.20.70.2
--------------------------------------------
CentMgmt::Device
Name                    hyd-lb-02.corp.example
Failover State          standby
Management Ip           172.20.20.81
Configsync Ip           172.20.70.3
"""

F5_UNKNOWN = 'Syntax Error: unexpected argument "garbage"'

# -- Citrix ADC (NetScaler) ---------------------------------------------------

NS_SHOW_VERSION = """\
        NetScaler NS13.1: Build 49.13.nc, Date: Feb 15 2026, 08:59:59   (64-bit)
        Done
"""

NS_SHOW_HOSTNAME = """\
        Hostname:  sec-adc-01
 Done
"""

NS_SHOW_HARDWARE = """\
        Platform: NSMPX-8900 8*CPU+4*F1X+E1K+2*E1K+2*CVM N3 250040
        Manufactured on: 3/2/2023
        CPU: 2100MHZ
        Host Id: 234f0d2a9c11
        Serial no: N7K3AB2CD4
        Encoded serial no: N7K3AB2CD4
        Netscaler UUID: 8b0aa1de-4f22-11ee-9c01-3cecef1a2b3c
 Done
"""

NS_SHOW_IP = """\
        Ipaddress        Traffic Domain  Type             Mode     Arp      Icmp     Vserver  State
        ---------        --------------  ----             ----     ---      ----     -------  ------
1)      172.20.20.90     0               NetScaler IP     Active   Enabled  Enabled  NA       Enabled
2)      172.20.80.1      0               SNIP             Active   Enabled  Enabled  NA       Enabled
3)      203.0.113.90     0               VIP              Active   Enabled  Enabled  Enabled  Enabled
 Done
"""

NS_SHOW_LB_VSERVER = """\
1)      vs-portal (203.0.113.90:443) - SSL      Type: ADDRESS
        State: UP
        Effective State: UP
        Health: 100.00% (2 UP/0 DOWN)

2)      vs-legacy (203.0.113.91:80) - HTTP      Type: ADDRESS
        State: DOWN
        Effective State: DOWN
        Health: 0.00% (0 UP/2 DOWN)
 Done
"""

NS_SHOW_HA_NODE = """\
1)      Node ID:      0
        IP:   172.20.20.90 (sec-adc-01)
        Node State: UP
        Master State: Primary
        Fail-Safe Mode: OFF
        INC State: DISABLED
        Sync State: ENABLED
        Propagation: ENABLED
        Enabled Interfaces : 1/1 1/2
        Disabled Interfaces : None
        HA MON ON Interfaces : 1/1 1/2

2)      Node ID:      1
        IP:   172.20.20.91
        Node State: UP
        Master State: Secondary
        Sync State: SUCCESS
 Done
"""

NS_UNKNOWN = "ERROR: No such command"

# -- A10 ACOS -----------------------------------------------------------------

A10_SHOW_VERSION = """\
Thunder Series Unified Application Service Gateway TH1040
        Advanced Core OS (ACOS) version 5.2.1-p6, build 114 (Jan-18-2026,04:32)
        Booted from Hard Disk primary image
        Serial Number: TH1040123456789
        aFleX version: 2.0.0
        Hard Disk primary
        Total System Memory 16299 Mbytes, Free Memory 9241 Mbytes
        Current time is Jul-14-2026, 06:59
        The system has been up 41 days, 3 hours, 40 minutes
"""

A10_SHOW_HOSTNAME = """\
Name: hyd-a10-01
"""

A10_SHOW_INTERFACES_BRIEF = """\
Port    Link  Dupl  Speed  Trunk Vlan MAC             IP Address          IPs  Name
------------------------------------------------------------------------------------
mgmt    Up    Full  1000   N/A   N/A  a10f.aabb.0001  172.20.20.95/24     1
1       Up    Full  10000  none  1    a10f.aabb.0002  172.20.90.1/24      1
2       Up    Full  10000  none  2    a10f.aabb.0003  203.0.113.95/24     1
3       Down  None  None   none  1    a10f.aabb.0004  0.0.0.0/0           0
"""

A10_SHOW_SLB_VIRTUAL = """\
Total Number of Virtual Services configured: 2
Virtual Server Name: vip-web            IP: 203.0.113.96:  All Ports
    Port 443  tcp: UP
        Service-group: sg-web  State: All Up

Virtual Server Name: vip-dns            IP: 203.0.113.97:  All Ports
    Port 53  udp: DOWN
        Service-group: sg-dns  State: All Down
"""

A10_UNKNOWN = "% Invalid input detected at '^' marker."


def f5_normal() -> dict:
    return {
        "show sys version": F5_SHOW_SYS_VERSION,
        "show sys hardware": F5_SHOW_SYS_HARDWARE,
        "list sys global-settings hostname": F5_LIST_SYS_GLOBAL,
        "list sys management-ip": F5_LIST_MGMT_IP,
        "list net self": F5_LIST_NET_SELF,
        "show net interface": F5_SHOW_NET_INTERFACE,
        "show ltm virtual": F5_SHOW_LTM_VIRTUAL,
        "show cm device": F5_SHOW_CM_DEVICE,
    }


def ns_normal() -> dict:
    return {
        "show ns version": NS_SHOW_VERSION,
        "show ns hostname": NS_SHOW_HOSTNAME,
        "show ns hardware": NS_SHOW_HARDWARE,
        "show ns ip": NS_SHOW_IP,
        "show lb vserver": NS_SHOW_LB_VSERVER,
        "show ha node": NS_SHOW_HA_NODE,
    }


def a10_normal() -> dict:
    return {
        "show version": A10_SHOW_VERSION,
        "show hostname": A10_SHOW_HOSTNAME,
        "show interfaces brief": A10_SHOW_INTERFACES_BRIEF,
        "show slb virtual-server": A10_SHOW_SLB_VIRTUAL,
    }
