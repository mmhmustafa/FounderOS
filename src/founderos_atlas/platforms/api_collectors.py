"""API evidence collection, coexisting with SSH (POLYGLOT Wave 2).

Where a platform exposes a production management API (FortiGate REST,
PAN-OS XML API), Atlas can collect the SAME canonical evidence over it —
richer where the API is richer, and always preserving the raw response
exactly as the device sent it. API collection NEVER replaces the SSH
driver: it merges into a ``DriverDiscovery`` produced by the platform's
driver, and where both sources describe the same fact the API's
structured answer wins while the CLI transcript remains in the raw
evidence.

The collectors are transport-injected: a caller supplies ``fetch(path)``
returning the response body. Atlas ships no HTTP client here and no
credential handling — the fetcher owns authentication, exactly as the
SSH transport owns the session. Raw responses are recorded under
``api:<path>`` keys beside the CLI outputs, so the Evidence Explorer
shows both collection channels with full provenance.

Maturity: TRANSCRIPT VALIDATED — parsers are exercised against sanitized
captures of real API response shapes; no live device API was available.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from founderos_atlas.firewall import (
    ACTION_ALLOW,
    ACTION_DENY,
    ACTION_UNKNOWN,
    FirewallEvidence,
    FirewallZone,
    SecurityPolicy,
    VpnTunnel,
)

from .base import DriverDiscovery

Fetcher = Callable[[str], str]


def _merge_metadata(discovery: DriverDiscovery, updates: Mapping[str, Any],
                    raw: Mapping[str, str]) -> DriverDiscovery:
    metadata = dict(discovery.result.device.metadata)
    metadata.update(updates)
    result = replace(
        discovery.result,
        device=replace(discovery.result.device, metadata=metadata),
    )
    return replace(
        discovery,
        result=result,
        raw_outputs={**discovery.raw_outputs, **raw},
    )


class FortiOSRestCollector:
    """FortiGate REST (``/api/v2``) evidence, merged beside the CLI's.

    Collected read-only monitor/cmdb endpoints:

    - ``/api/v2/monitor/system/status``   — identity corroboration
    - ``/api/v2/cmdb/firewall/policy``    — the policy set (richer than CLI:
      explicit ``status``/``action`` fields, UUIDs, hit counts when enabled)
    - ``/api/v2/monitor/vpn/ipsec``       — tunnel state with phase detail
    - ``/api/v2/cmdb/system/zone``        — zone → interface bindings
    """

    STATUS = "/api/v2/monitor/system/status"
    POLICIES = "/api/v2/cmdb/firewall/policy"
    VPNS = "/api/v2/monitor/vpn/ipsec"
    ZONES = "/api/v2/cmdb/system/zone"

    def collect(self, discovery: DriverDiscovery, fetch: Fetcher) -> DriverDiscovery:
        raw: dict[str, str] = {}
        payloads: dict[str, Any] = {}
        for path in (self.STATUS, self.POLICIES, self.VPNS, self.ZONES):
            try:
                body = fetch(path)
            except Exception as error:  # noqa: BLE001 - recorded, not raised
                raw[f"api:{path}"] = f"<unavailable: {str(error)[:120]}>"
                continue
            raw[f"api:{path}"] = body
            try:
                payloads[path] = json.loads(body)
            except (ValueError, TypeError):
                continue

        evidence = self._evidence(payloads)
        updates: dict[str, Any] = {
            "api_collection": {
                "channel": "fortios-rest",
                "endpoints": sorted(
                    key.removeprefix("api:") for key in raw
                ),
                "merged": not evidence.is_empty,
            },
        }
        if not evidence.is_empty:
            merged = _merge_firewall_evidence(
                discovery.result.device.metadata.get("firewall_evidence"),
                evidence,
            )
            updates["firewall_evidence"] = merged
        return _merge_metadata(discovery, updates, raw)

    def _evidence(self, payloads: Mapping[str, Any]) -> FirewallEvidence:
        zones = tuple(
            FirewallZone(
                name=str(item.get("name")),
                interfaces=tuple(
                    str(member.get("interface-name"))
                    for member in item.get("interface") or ()
                ),
            )
            for item in _results(payloads.get(self.ZONES))
        )
        policies = tuple(
            SecurityPolicy(
                policy_id=str(item.get("policyid")),
                name=item.get("name"),
                from_zones=tuple(
                    str(z.get("name")) for z in item.get("srcintf") or ()
                ),
                to_zones=tuple(
                    str(z.get("name")) for z in item.get("dstintf") or ()
                ),
                sources=tuple(
                    str(a.get("name")) for a in item.get("srcaddr") or ()
                ),
                destinations=tuple(
                    str(a.get("name")) for a in item.get("dstaddr") or ()
                ),
                services=tuple(
                    str(s.get("name")) for s in item.get("service") or ()
                ),
                action=(
                    ACTION_ALLOW
                    if str(item.get("action")) == "accept" else ACTION_DENY
                ),
                enabled=str(item.get("status", "enable")) == "enable",
                log=str(item.get("logtraffic", "")) not in ("", "disable"),
            )
            for item in _results(payloads.get(self.POLICIES))
        )
        vpns = tuple(
            VpnTunnel(
                name=str(item.get("name")),
                tunnel_type="ipsec",
                remote_gateway=item.get("rgwy"),
                status=(
                    "up" if any(
                        proxy.get("status") == "up"
                        for proxy in item.get("proxyid") or ()
                    ) else "down"
                ),
            )
            for item in _results(payloads.get(self.VPNS))
        )
        return FirewallEvidence(
            zones=zones, security_policies=policies, vpns=vpns,
            source_commands=tuple(
                f"api:{path}" for path in (
                    self.ZONES, self.POLICIES, self.VPNS,
                ) if path in payloads
            ),
        )


class PanOsXmlApiCollector:
    """PAN-OS XML API (``/api?type=op``) evidence, merged beside the CLI's.

    Collected read-only op commands (the XML forms of the same evidence
    the SSH driver reads):

    - ``<show><system><info/></system></show>``       — identity
    - ``<show><vpn><ipsec-sa/></vpn></show>``          — tunnel state
    - ``<show><high-availability><state/></high-availability></show>``
    """

    SYSTEM = "type=op&cmd=<show><system><info/></system></show>"
    VPNS = "type=op&cmd=<show><vpn><ipsec-sa/></vpn></show>"
    HA = (
        "type=op&cmd=<show><high-availability><state/>"
        "</high-availability></show>"
    )

    def collect(self, discovery: DriverDiscovery, fetch: Fetcher) -> DriverDiscovery:
        raw: dict[str, str] = {}
        bodies: dict[str, str] = {}
        for path in (self.SYSTEM, self.VPNS, self.HA):
            try:
                body = fetch(path)
            except Exception as error:  # noqa: BLE001
                raw[f"api:{path}"] = f"<unavailable: {str(error)[:120]}>"
                continue
            raw[f"api:{path}"] = body
            bodies[path] = body

        updates: dict[str, Any] = {
            "api_collection": {
                "channel": "panos-xmlapi",
                "endpoints": sorted(
                    key.removeprefix("api:") for key in raw
                ),
                "merged": bool(bodies),
            },
        }
        serial = _xml_text(bodies.get(self.SYSTEM, ""), "serial")
        if serial:
            updates["api_serial"] = serial
        tunnels = _xml_ipsec(bodies.get(self.VPNS, ""))
        if tunnels:
            merged = _merge_firewall_evidence(
                discovery.result.device.metadata.get("firewall_evidence"),
                FirewallEvidence(
                    vpns=tunnels,
                    source_commands=(f"api:{self.VPNS}",),
                ),
            )
            updates["firewall_evidence"] = merged
        return _merge_metadata(discovery, updates, raw)


def _results(payload) -> tuple[dict, ...]:
    if not isinstance(payload, Mapping):
        return ()
    results = payload.get("results")
    if isinstance(results, list):
        return tuple(item for item in results if isinstance(item, Mapping))
    return ()


def _xml_text(body: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>([^<]+)</{tag}>", body or "")
    return match.group(1).strip() if match else None


def _xml_ipsec(body: str) -> tuple[VpnTunnel, ...]:
    tunnels: list[VpnTunnel] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", body or "", re.DOTALL):
        name = _xml_text(entry, "name")
        if not name:
            continue
        tunnels.append(VpnTunnel(
            name=name,
            tunnel_type="ipsec",
            remote_gateway=_xml_text(entry, "peerip"),
            status=(_xml_text(entry, "state") or "unknown").casefold(),
        ))
    return tuple(tunnels)


def _merge_firewall_evidence(existing, api_evidence: FirewallEvidence) -> dict:
    """Prefer the API's richer answer per section; keep the CLI's where the
    API produced nothing. Raw transcripts of both channels stay preserved,
    so nothing is lost by preferring structure."""

    if not isinstance(existing, Mapping):
        return api_evidence.to_dict()
    merged = dict(existing)
    api = api_evidence.to_dict()
    for key in ("zones", "security_policies", "nat_rules", "vpns",
                "virtual_contexts", "ha_peers"):
        if api.get(key):
            merged[key] = api[key]
    merged["source_commands"] = sorted(
        {*existing.get("source_commands", ()), *api.get("source_commands", ())}
    )
    # Recompute the summary over the merged sections.
    merged["summary"] = _summarize(merged)
    return merged


def _summarize(evidence: Mapping[str, Any]) -> dict[str, Any]:
    actions: dict[str, int] = {}
    default_action = ACTION_UNKNOWN
    for policy in evidence.get("security_policies") or ():
        action = str(policy.get("action") or ACTION_UNKNOWN)
        actions[action] = actions.get(action, 0) + 1
        if policy.get("enabled", True):
            default_action = action
    vpns = evidence.get("vpns") or ()
    return {
        "zone_count": len(evidence.get("zones") or ()),
        "policy_count": len(evidence.get("security_policies") or ()),
        "policies_by_action": dict(sorted(actions.items())),
        "nat_rule_count": len(evidence.get("nat_rules") or ()),
        "vpn_count": len(vpns),
        "vpns_up": sum(
            1 for tunnel in vpns if tunnel.get("status") == "up"
        ),
        "virtual_context_count": len(evidence.get("virtual_contexts") or ()),
        "ha_mode": evidence.get("ha_mode"),
        "ha_peer_count": len(evidence.get("ha_peers") or ()),
        "default_action": default_action,
    }
