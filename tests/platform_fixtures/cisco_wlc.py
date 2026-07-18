"""Sanitized Cisco WLC (AireOS 8.10) transcripts.

TRANSCRIPT VALIDATED fixtures with documentation addressing throughout.
"""

SHOW_SYSINFO = """\
Manufacturer's Name.............................. Cisco Systems Inc.
Product Name..................................... Cisco Controller
Product Version.................................. 8.10.190.0
RTOS Version..................................... 8.10.190.0
Bootloader Version............................... 8.5.103.0
Emergency Image Version.......................... 8.5.103.0
OUI File Last Update Time........................ Sun Sep 07 10:44:07 IST 2025

Build Type....................................... DATA + WPS

System Name...................................... hyd-wlc-01
System Location.................................. hyderabad-dc
System Contact...................................
System ObjectID.................................. 1.3.6.1.4.1.9.1.2427
Redundancy Mode.................................. SSO
IP Address....................................... 172.20.20.70
IPv6 Address..................................... ::
System Up Time................................... 41 days 3 hrs 27 mins 12 secs
System Timezone Location......................... (GMT+5:30) Colombo, New Delhi
System Stats Realtime Interval................... 5
System Stats Normal Interval..................... 180

Configured Country............................... IN  - India
State of 802.11b Network......................... Enabled
State of 802.11a Network......................... Enabled
Number of WLANs.................................. 4
Number of Active Clients......................... 213

Burned-in MAC Address............................ 50:0F:80:AA:BB:00
Maximum number of APs supported.................. 150
"""

SHOW_INVENTORY = """\
Burned-in MAC Address............................ 50:0F:80:AA:BB:00
Power Supply 1................................... Present, OK
Power Supply 2................................... Absent

PID: AIR-CT5520-K9, VID: V04, SN: FCH2233W0AB
"""

SHOW_INTERFACE_SUMMARY = """\
 Number of Interfaces.......................... 4

Interface Name                   Port Vlan Id  IP Address      Type    Ap Mgr Guest
-------------------------------- ---- -------- --------------- ------- ------ -----
management                       1    70       172.20.20.70    Static  Yes    No
redundancy-management            1    70       172.20.20.71    Static  No     No
service-port                     N/A  N/A      192.168.100.70  Static  No     No
virtual                          N/A  N/A      192.0.2.1       Static  No     No
"""

SHOW_AP_SUMMARY = """\
Number of APs.................................... 3

Global AP User Name.............................. admin
Global AP Dot1x User Name........................ Not Configured

AP Name             Slots  AP Model              Ethernet MAC       Location          Country  IP Address       Clients  DSE Location
------------------  -----  --------------------  -----------------  ----------------  -------  ---------------  -------  --------------
hyd-ap-lobby        2      AIR-AP2802I-D-K9      70:0f:6a:11:22:01  lobby             IN       172.20.62.11     37       [0,0,0]
hyd-ap-floor1       2      AIR-AP2802I-D-K9      70:0f:6a:11:22:02  floor-1           IN       172.20.62.12     101      [0,0,0]
hyd-ap-floor2       2      AIR-AP2802I-D-K9      70:0f:6a:11:22:03  floor-2           IN       172.20.62.13     75       [0,0,0]
"""

SHOW_WLAN_SUMMARY = """\
Number of WLANs.................................. 4

WLAN ID  WLAN Profile Name / SSID               Status    Interface Name        PMIPv6 Mobility
-------  -------------------------------------  --------  --------------------  ---------------
1        corp / corp-wifi                       Enabled   management            none
2        guest / guest-wifi                     Enabled   management            none
3        iot / iot-devices                      Enabled   management            none
4        lab / lab-wifi                         Disabled  management            none
"""

SHOW_CDP_NEIGHBORS = """\
AP Name             AP IP           Neighbor Name    Neighbor Address  Neighbor Port
------------------  --------------  ---------------  ----------------  ----------------
hyd-ap-lobby        172.20.62.11    hyd-agg-01       172.20.20.60      1/1/5
hyd-ap-floor1       172.20.62.12    hyd-agg-01       172.20.20.60      1/1/6
"""

SHOW_REDUNDANCY = """\
Redundancy Mode = SSO ENABLED
     Local State = ACTIVE
      Peer State = STANDBY HOT
            Unit = Primary
         Unit ID = 50:0F:80:AA:BB:00
Redundancy State = SSO
    Mobility MAC = 50:0F:80:AA:BB:00

Redundancy Management IP Address................. 172.20.20.71
Peer Redundancy Management IP Address............ 172.20.20.72
Redundancy Port IP Address....................... 169.254.20.71
Peer Service Port IP Address..................... 192.168.100.71
"""

SHOW_RUNNING_CONFIG = """\
802.11a cac voice sip bandwidth 64
interface address management 172.20.20.70 255.255.255.0 172.20.20.1
interface address virtual 192.0.2.1
wlan create 1 corp corp-wifi
wlan create 2 guest guest-wifi
"""

UNKNOWN = "Incorrect usage.  Use the '?' or <TAB> key to list commands."


def normal() -> dict:
    return {
        "show sysinfo": SHOW_SYSINFO,
        "show inventory": SHOW_INVENTORY,
        "show interface summary": SHOW_INTERFACE_SUMMARY,
        "show ap summary": SHOW_AP_SUMMARY,
        "show wlan summary": SHOW_WLAN_SUMMARY,
        "show ap cdp neighbors all": SHOW_CDP_NEIGHBORS,
        "show redundancy summary": SHOW_REDUNDANCY,
        "show run-config commands": SHOW_RUNNING_CONFIG,
    }
