"""The Atlas Starter Policy Pack (PR-047 Part 2).

Twelve policies that exercise every operator, category, evidence kind, and
disposition (pass / fail / warning / unknown / not-applicable) — enough to
*validate the architecture*, not to be exhaustive compliance. Each is pure
data; the reasoning is the CORTEX engine's.

A note on honesty across platforms: several of these will legitimately report
``fail`` or ``unknown`` on an FRRouting device, because FRR does not express
NTP, AAA, SNMP, or password-service directives in its running-config the way
IOS does. That is the correct, evidence-based result — Atlas reports what it can
see and says Unknown where it cannot, rather than assuming compliance.
"""

from __future__ import annotations

from founderos_atlas.reasoning import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)

from ..matcher import (
    MATCH_REGEX,
    OP_ANY_PRESENT,
    OP_CONDITIONAL_PRESENT,
    OP_INTERFACES_SHUTDOWN,
    PolicyCheck,
)
from ..models import (
    CATEGORY_CONFIGURATION,
    CATEGORY_IDENTITY,
    CATEGORY_MANAGEMENT,
    CATEGORY_OPERATIONAL,
    CATEGORY_ROUTING,
    CATEGORY_SECURITY,
    Policy,
    PolicyPack,
)

_AUTHOR = "Atlas Starter Pack"
_VERSION = "1.0"


STARTER_POLICIES: tuple[Policy, ...] = (
    Policy(
        policy_id="STD-SSH-001",
        name="SSH Management Access",
        description="The device must be reachable and manageable over SSH.",
        category=CATEGORY_SECURITY,
        severity=SEVERITY_HIGH,
        check=PolicyCheck(
            evidence="access-transport",
            operator=OP_ANY_PRESENT,
            patterns=("ssh",),
        ),
        evidence_required=("access-transport",),
        reasoning_strategy="transport-observation",
        expected_state="Atlas should be able to authenticate to the device over SSH.",
        recommendation="Enable the SSH server and disable Telnet for management.",
        remediation="Configure and enable the SSH daemon; restrict management to SSH only.",
        tags=("access", "encryption", "management-plane"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-NTP-001",
        name="NTP Configured",
        description="The device should synchronise time from an NTP source.",
        category=CATEGORY_MANAGEMENT,
        severity=SEVERITY_LOW,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=("ntp server", "ntp peer"),
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="At least one NTP server or peer should be configured.",
        recommendation="Configure at least one reliable NTP server.",
        remediation="Add 'ntp server <address>' pointing at an authoritative time source.",
        tags=("time", "management-plane"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-LOG-001",
        name="Logging Configured",
        description="The device should emit logs to a collector or local file.",
        category=CATEGORY_MANAGEMENT,
        severity=SEVERITY_LOW,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=("logging ", "log syslog", "log file", "log stdout"),
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="A logging destination (syslog, file, or host) should be configured.",
        recommendation="Configure logging to a central syslog collector.",
        remediation="Add a 'logging <host>' or 'log syslog' directive.",
        tags=("observability", "management-plane"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-AAA-001",
        name="AAA Present",
        description="Authentication, authorization and accounting should be configured.",
        category=CATEGORY_SECURITY,
        severity=SEVERITY_MEDIUM,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=("aaa new-model", "aaa authentication", "aaa authorization"),
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="AAA should be enabled for centralized access control.",
        recommendation="Enable AAA and integrate with a central identity source.",
        remediation="Configure 'aaa new-model' and the relevant authentication methods.",
        tags=("aaa", "identity", "management-plane"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-SNMP-001",
        name="SNMP Configured",
        description="The device should expose SNMP for monitoring.",
        category=CATEGORY_MANAGEMENT,
        severity=SEVERITY_LOW,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=("snmp-server", "snmp "),
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="SNMP (ideally v3) should be configured for monitoring.",
        recommendation="Configure SNMPv3 with authentication and privacy.",
        remediation="Add 'snmp-server' configuration, preferring SNMPv3.",
        tags=("monitoring", "management-plane"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-IFACE-001",
        name="Unused Interfaces Shut Down",
        description="Enabled interfaces should be addressed, described, or shut down.",
        category=CATEGORY_OPERATIONAL,
        severity=SEVERITY_LOW,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_INTERFACES_SHUTDOWN,
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-structure",
        expected_state="No interface should be administratively up yet unused (no address, no description).",
        recommendation="Shut down interfaces that are not in service.",
        remediation="Apply 'shutdown' to unused interfaces, or document them with a description.",
        tags=("hardening", "attack-surface"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-LOOP-001",
        name="Loopback Interface Present",
        description="A loopback interface should exist as a stable device identity.",
        category=CATEGORY_CONFIGURATION,
        severity=SEVERITY_LOW,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=(r"interface\s+lo\b", r"interface\s+loopback\d*"),
            match=MATCH_REGEX,
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="At least one loopback interface should be configured.",
        recommendation="Configure a loopback interface for a stable router identity.",
        remediation="Add 'interface loopback0' with a /32 address.",
        tags=("identity", "routing"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-HOST-001",
        name="Hostname Configured",
        description="The device must have a hostname set.",
        category=CATEGORY_IDENTITY,
        severity=SEVERITY_MEDIUM,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=(r"^hostname\s+\S+",),
            match=MATCH_REGEX,
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="A non-default hostname should be configured.",
        recommendation="Set a meaningful, unique hostname.",
        remediation="Configure 'hostname <name>'.",
        tags=("identity",),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-DOMAIN-001",
        name="Domain Name Configured",
        description="A DNS domain name should be configured.",
        category=CATEGORY_IDENTITY,
        severity=SEVERITY_LOW,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=(r"ip domain[- ]name\s+\S+", r"domain-name\s+\S+", r"dns\s+domain"),
            match=MATCH_REGEX,
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="A DNS domain name should be configured.",
        recommendation="Configure the DNS domain name.",
        remediation="Add 'ip domain-name <domain>'.",
        tags=("identity", "dns"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-PWENC-001",
        name="Password Encryption Enabled",
        description="Stored passwords should be encrypted at rest in the configuration.",
        category=CATEGORY_SECURITY,
        severity=SEVERITY_MEDIUM,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_ANY_PRESENT,
            patterns=("service password-encryption",),
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-presence",
        expected_state="Password encryption service should be enabled.",
        recommendation="Enable password encryption so credentials are not stored in clear text.",
        remediation="Configure 'service password-encryption'.",
        tags=("hardening", "credentials"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-BGPRID-001",
        name="BGP Router ID Present",
        description="Where BGP is configured, an explicit router-id should be set.",
        category=CATEGORY_ROUTING,
        severity=SEVERITY_MEDIUM,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_CONDITIONAL_PRESENT,
            antecedent=(r"router bgp\s+\d+",),
            patterns=(r"bgp router-id\s+\S+",),
            match=MATCH_REGEX,
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-conditional",
        expected_state="If BGP is configured, 'bgp router-id' should be set explicitly.",
        recommendation="Set an explicit BGP router-id for deterministic peering identity.",
        remediation="Add 'bgp router-id <loopback-address>' under 'router bgp'.",
        tags=("routing", "bgp", "stability"),
        version=_VERSION,
        author=_AUTHOR,
    ),
    Policy(
        policy_id="STD-OSPFRID-001",
        name="OSPF Router ID Present",
        description="Where OSPF is configured, an explicit router-id should be set.",
        category=CATEGORY_ROUTING,
        severity=SEVERITY_MEDIUM,
        check=PolicyCheck(
            evidence="running-config",
            operator=OP_CONDITIONAL_PRESENT,
            antecedent=(r"router ospf",),
            patterns=(r"ospf router-id\s+\S+", r"router-id\s+\S+"),
            match=MATCH_REGEX,
        ),
        evidence_required=("running-config",),
        reasoning_strategy="configuration-conditional",
        expected_state="If OSPF is configured, an explicit router-id should be set.",
        recommendation="Set an explicit OSPF router-id for deterministic identity.",
        remediation="Add 'ospf router-id <loopback-address>' under 'router ospf'.",
        tags=("routing", "ospf", "stability"),
        version=_VERSION,
        author=_AUTHOR,
    ),
)


STARTER_PACK = PolicyPack(
    pack_id="atlas-starter",
    name="Atlas Starter Policy Pack",
    description=(
        "A representative set of configuration, routing, security, identity, "
        "management and operational policies — enough to validate the reasoning "
        "framework end to end."
    ),
    version=_VERSION,
    author=_AUTHOR,
    policies=STARTER_POLICIES,
)
