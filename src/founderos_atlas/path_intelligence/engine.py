"""Deterministic path construction and hop-by-hop validation.

``investigate_path`` answers: *can the source device reach the destination
device across the discovered topology — and if not, where exactly does
communication stop, and why?*

Rules of evidence (identical to the rest of Atlas):

- The path is constructed only from discovered topology edges (CDP/LLDP
  and known links in the current snapshot). No packet is simulated, no
  traceroute is run, no route is guessed.
- When more than one equally short path exists, Atlas reports the
  ambiguity and every candidate — it never picks one silently.
- Every hop is validated against collected evidence: device exists →
  interfaces exist → operational state → link state → management
  reachability. The first deterministic failure stops the walk; later
  hops are honestly marked "not evaluated", never assumed healthy.
- Confidence is documented per hop, reduced by stale or missing
  evidence, and capped below 100%.
"""

from __future__ import annotations

from collections import deque
from hashlib import sha256

from .models import (
    FAILURE_ADMIN_SHUTDOWN,
    FAILURE_AMBIGUOUS_TOPOLOGY,
    FAILURE_DEVICE_UNREACHABLE,
    FAILURE_DISCOVERY_INCOMPLETE,
    FAILURE_INTERFACE_DOWN,
    FAILURE_UNKNOWN_DESTINATION,
    FAILURE_UNKNOWN_DEVICE,
    FAILURE_UNKNOWN_PATH,
    HOP_FAILED,
    HOP_PASS,
    HOP_UNKNOWN,
    HOP_WARNING,
    HopResult,
    InvestigationStep,
    PathInvestigationResult,
    RESULT_AMBIGUOUS,
    RESULT_CONNECTED,
    RESULT_FAILED,
    RESULT_UNKNOWN,
)


CONFIDENCE_CAP = 0.95
CONFIDENCE_DIRECT_EVIDENCE = 0.9   # state read from the device this snapshot
CONFIDENCE_PARTIAL_EVIDENCE = 0.5  # some evidence missing for the hop
CONFIDENCE_NOT_EVALUATED = 0.2    # investigation stopped before this hop
STALE_PENALTY = 0.15               # snapshot older than the freshness window
MAX_CANDIDATE_PATHS = 4


def investigate_path(
    source: str,
    destination: str,
    *,
    snapshot: dict | None,
    generated_at: str,
    profile_id: str | None = None,
    fresh: bool = True,
    failed_hosts: tuple[str, ...] = (),
    captured_config_devices: tuple[str, ...] = (),
) -> PathInvestigationResult:
    """Investigate device-to-device connectivity from discovered evidence.

    ``failed_hosts`` are hosts the most recent discovery could not reach
    (management-plane evidence). ``captured_config_devices`` are devices
    whose running configuration Atlas has captured — cited so a failed
    hop can point the engineer at reviewable configuration evidence.
    """

    builder = _Investigation(
        source=source.strip(),
        destination=destination.strip(),
        snapshot=snapshot if isinstance(snapshot, dict) else None,
        generated_at=generated_at,
        profile_id=profile_id,
        fresh=bool(fresh),
        failed_hosts=frozenset(str(host).casefold() for host in failed_hosts),
        captured_configs=frozenset(
            str(name).casefold() for name in captured_config_devices
        ),
    )
    return builder.run()


# -- implementation --------------------------------------------------------------


class _Investigation:
    def __init__(
        self,
        *,
        source: str,
        destination: str,
        snapshot: dict | None,
        generated_at: str,
        profile_id: str | None,
        fresh: bool,
        failed_hosts: frozenset[str],
        captured_configs: frozenset[str],
    ) -> None:
        self.source = source
        self.destination = destination
        self.snapshot = snapshot
        self.generated_at = generated_at
        self.profile_id = profile_id
        self.fresh = fresh
        self.failed_hosts = failed_hosts
        self.captured_configs = captured_configs
        self.steps: list[InvestigationStep] = []
        self.unknowns: list[str] = []
        self.evidence_refs: list[str] = []
        self.recommendations: list[str] = []
        # Evidence indexes built from the snapshot.
        self.devices: dict[str, dict] = {}
        self.neighbor_only: dict[str, list[str]] = {}
        self.links: dict[tuple[str, str], list[dict]] = {}
        self.adjacency: dict[str, set[str]] = {}

    # -- top level ---------------------------------------------------------

    def run(self) -> PathInvestigationResult:
        if self.snapshot is None or not self.snapshot.get("devices"):
            return self._no_evidence_result()
        self._index_snapshot()
        self.evidence_refs.append(self._snapshot_ref())
        if not self.fresh:
            self.unknowns.append(
                "The topology snapshot is older than the freshness window; "
                "the network may have changed since this evidence was collected."
            )

        source_key = self._resolve_device(self.source)
        destination_key = self._resolve_device(self.destination)
        problem = self._check_endpoints(source_key, destination_key)
        if problem is not None:
            return problem
        assert source_key is not None and destination_key is not None

        if source_key == destination_key:
            return self._single_device_result(source_key)

        paths = self._shortest_paths(source_key, destination_key)
        if not paths:
            return self._no_path_result(source_key, destination_key)
        if len(paths) > 1:
            # Multiple equal-cost paths are REDUNDANCY, not ambiguity: the
            # devices are connected via several independent paths (good
            # design). Reachability is a strong YES; only *which* path a
            # given flow takes is unknown without routing evidence — a
            # footnote, never a "communication stops" failure.
            return self._redundant_paths_result(paths)
        return self._walk_path(paths[0])

    # -- snapshot indexing ---------------------------------------------------

    def _index_snapshot(self) -> None:
        assert self.snapshot is not None
        id_to_host: dict[str, str] = {}
        ip_to_key: dict[str, str] = {}
        for device in self.snapshot.get("devices") or ():
            if not isinstance(device, dict):
                continue
            hostname = str(device.get("hostname") or "").strip()
            if not hostname:
                continue
            key = hostname.casefold()
            self.devices[key] = dict(device)
            id_to_host[str(device.get("device_id"))] = hostname
            management_ip = str(device.get("management_ip") or "").strip()
            if management_ip:
                ip_to_key.setdefault(management_ip.casefold(), key)
        for edge in self.snapshot.get("edges") or ():
            if not isinstance(edge, dict):
                continue
            local = id_to_host.get(
                str(edge.get("local_device_id")), str(edge.get("local_device_id"))
            )
            remote = str(edge.get("remote_hostname") or "").strip()
            if not local or not remote:
                continue
            local_key = local.casefold()
            remote_key = remote.casefold()
            if remote_key not in self.devices:
                # PR-043.1: a routing adjacency names its peer by router
                # ID or address. When that value exactly matches a
                # DISCOVERED device's management address, the edge
                # resolves onto it — deterministic address-identity
                # evidence, never a name guess.
                remote_key = ip_to_key.get(remote_key, remote_key)
            if remote_key not in self.devices:
                self.neighbor_only.setdefault(remote_key, []).append(local)
            pair = tuple(sorted((local_key, remote_key)))
            record = {
                "a": local_key,
                "b": remote_key,
                "a_interface": str(edge.get("local_interface") or "") or None,
                "b_interface": str(edge.get("remote_interface") or "") or None,
                "protocol": str(edge.get("protocol") or "").strip() or "unknown",
            }
            bucket = self.links.setdefault((pair[0], pair[1]), [])
            if not any(
                item["a"] == record["a"]
                and item["a_interface"] == record["a_interface"]
                and item["b_interface"] == record["b_interface"]
                for item in bucket
            ):
                bucket.append(record)
            self.adjacency.setdefault(local_key, set()).add(remote_key)
            self.adjacency.setdefault(remote_key, set()).add(local_key)
        # PR-043.8 (CONSISTENCY): Investigation walks the SAME Enterprise
        # Knowledge Graph Topology renders. Evidence Correlation resolves
        # peer addresses (a BGP peer, an OSPF adjacency address) onto the
        # device that owns them via the address-ownership index — links
        # raw edges leave dangling. Consuming the fused relationships here
        # means any routed path visible in Topology is walkable here too.
        metadata = dict(self.snapshot.get("metadata") or {})
        for fused in metadata.get("correlated_relationships") or ():
            if not isinstance(fused, dict):
                continue
            local = id_to_host.get(str(fused.get("left_device_id")))
            remote = id_to_host.get(str(fused.get("right_device_id")))
            if not local or not remote:
                continue  # a fused pair must join two discovered devices
            local_key = local.casefold()
            remote_key = remote.casefold()
            pair = tuple(sorted((local_key, remote_key)))
            record = {
                "a": local_key,
                "b": remote_key,
                "a_interface": str(fused.get("left_interface") or "") or None,
                "b_interface": str(fused.get("right_interface") or "") or None,
                "protocol": str(
                    fused.get("relationship_type") or "correlated"
                ),
                "correlated": True,
                "confidence": int(fused.get("confidence") or 0),
            }
            bucket = self.links.setdefault((pair[0], pair[1]), [])
            if not any(
                item["a"] == record["a"]
                and item["a_interface"] == record["a_interface"]
                and item["b_interface"] == record["b_interface"]
                and item.get("correlated")
                for item in bucket
            ):
                bucket.append(record)
            self.adjacency.setdefault(local_key, set()).add(remote_key)
            self.adjacency.setdefault(remote_key, set()).add(local_key)

    def _resolve_device(self, requested: str) -> str | None:
        wanted = requested.casefold()
        if wanted in self.devices or wanted in self.neighbor_only:
            return wanted
        for key, device in sorted(self.devices.items()):
            if str(device.get("management_ip") or "").casefold() == wanted:
                return key
        return None

    def _display_name(self, key: str) -> str:
        device = self.devices.get(key)
        if device is not None:
            return str(device.get("hostname"))
        # Neighbor-only devices keep the announced name's casing where known.
        assert self.snapshot is not None
        for edge in self.snapshot.get("edges") or ():
            if isinstance(edge, dict) and str(
                edge.get("remote_hostname") or ""
            ).casefold() == key:
                return str(edge.get("remote_hostname"))
        return key

    # -- endpoint checks -------------------------------------------------------

    def _check_endpoints(
        self, source_key: str | None, destination_key: str | None
    ) -> PathInvestigationResult | None:
        if source_key is None:
            self._step(
                f"Locate source device '{self.source}'",
                HOP_FAILED,
                f"No device named '{self.source}' (by hostname or management "
                "address) exists in the discovered topology.",
            )
            return self._finish(
                status=RESULT_UNKNOWN,
                path=(),
                hops=(),
                failure_type=FAILURE_UNKNOWN_DEVICE,
                failure_summary=(
                    f"The source device '{self.source}' is not present in the "
                    "current topology evidence."
                ),
                confidence=CONFIDENCE_PARTIAL_EVIDENCE,
                recommendations=(
                    f"Verify the device name '{self.source}' — Atlas matches "
                    "discovered hostnames and management addresses.",
                    "Run a fresh discovery if this device was added recently.",
                ),
            )
        self._step(
            f"Locate source device {self._display_name(source_key)}",
            HOP_PASS,
            "Present in the current topology snapshot.",
            evidence=(self._device_ref(source_key),),
        )
        if destination_key is None:
            self._step(
                f"Locate destination device '{self.destination}'",
                HOP_FAILED,
                f"No device named '{self.destination}' (by hostname or "
                "management address) exists in the discovered topology.",
            )
            return self._finish(
                status=RESULT_UNKNOWN,
                path=(),
                hops=(),
                failure_type=FAILURE_UNKNOWN_DESTINATION,
                failure_summary=(
                    f"The destination device '{self.destination}' is not "
                    "present in the current topology evidence."
                ),
                confidence=CONFIDENCE_PARTIAL_EVIDENCE,
                recommendations=(
                    f"Verify the device name '{self.destination}'.",
                    "Run a fresh discovery — the destination may not have "
                    "been discovered yet (check seeds, boundary, and "
                    "credentials).",
                ),
            )
        self._step(
            f"Locate destination device {self._display_name(destination_key)}",
            HOP_PASS if destination_key in self.devices else HOP_WARNING,
            "Present in the current topology snapshot."
            if destination_key in self.devices
            else "Known only from neighbor announcements — Atlas has not "
            "discovered this device directly.",
            evidence=(self._device_ref(destination_key),),
        )
        return None

    # -- path construction ------------------------------------------------------

    def _shortest_paths(self, source: str, destination: str) -> list[list[str]]:
        """All shortest device sequences, deterministically ordered.

        Breadth-first over sorted neighbors; parents recorded per level so
        equal-cost alternatives are enumerated, not hidden.
        """

        distance: dict[str, int] = {source: 0}
        parents: dict[str, list[str]] = {source: []}
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            if current == destination:
                continue
            for neighbor in sorted(self.adjacency.get(current, ())):
                if neighbor not in distance:
                    distance[neighbor] = distance[current] + 1
                    parents[neighbor] = [current]
                    queue.append(neighbor)
                elif distance[neighbor] == distance[current] + 1:
                    parents[neighbor].append(current)
        if destination not in distance:
            return []
        paths: list[list[str]] = []

        def build(node: str, suffix: list[str]) -> None:
            if len(paths) >= MAX_CANDIDATE_PATHS:
                return
            if node == source:
                paths.append([source, *suffix])
                return
            for parent in sorted(parents[node]):
                build(parent, [node, *suffix])

        build(destination, [])
        return paths

    # -- hop validation ----------------------------------------------------------

    def _walk_path(self, path: list[str]) -> PathInvestigationResult:
        names = [self._display_name(key) for key in path]
        self._step(
            "Construct path from topology evidence",
            HOP_PASS,
            "Known path: " + " → ".join(names) + f" ({len(path) - 1} link(s), "
            "from discovered neighbor adjacency).",
            evidence=(self._snapshot_ref(),),
        )
        hops: list[HopResult] = []
        failure: HopResult | None = None
        for index, key in enumerate(path):
            if failure is not None:
                hops.append(self._not_evaluated_hop(len(hops) + 1, key, failure))
                continue
            ingress = self._link_interface(key, path[index - 1]) if index else None
            egress = (
                self._link_interface(key, path[index + 1])
                if index + 1 < len(path)
                else None
            )
            hop = self._validate_hop(
                hop_number=len(hops) + 1,
                key=key,
                ingress=ingress,
                egress=egress,
            )
            hops.append(hop)
            self._step(
                f"Validate {self._display_name(key)}"
                + (f" (via {hop.ingress_interface})" if hop.ingress_interface else ""),
                hop.status,
                hop.explanation,
                evidence=hop.evidence,
            )
            if hop.status == HOP_FAILED:
                failure = hop
        if failure is not None:
            return self._failed_walk_result(path, hops, failure)
        warnings = [hop for hop in hops if hop.status == HOP_WARNING]
        summary_status = RESULT_CONNECTED
        confidence = self._overall_confidence(hops)
        self._step(
            "Conclusion",
            HOP_PASS if not warnings else HOP_WARNING,
            "Every hop on the known path passed validation."
            if not warnings
            else "The path is validated end to end, with "
            f"{len(warnings)} hop(s) carrying incomplete evidence (see "
            "warnings).",
        )
        recommendations = []
        if warnings:
            recommendations.append(
                "Run a fresh discovery to complete the missing evidence noted "
                "on the warning hops."
            )
        recommendations.append(
            "No known deterministic fault on this path. If communication "
            "still fails, the cause lies in evidence Atlas does not collect "
            "yet (routing, ACLs, host configuration) — collect that evidence "
            "next rather than re-checking these hops."
        )
        return self._finish(
            status=summary_status,
            path=tuple(names),
            hops=tuple(hops),
            failure_type=None,
            failure_summary=None,
            confidence=confidence,
            recommendations=tuple(recommendations),
        )

    def _validate_hop(
        self,
        *,
        hop_number: int,
        key: str,
        ingress: str | None,
        egress: str | None,
    ) -> HopResult:
        name = self._display_name(key)
        evidence: list[str] = []
        missing: list[str] = []
        device = self.devices.get(key)

        management_state, mgmt_note = self._management_state(key)
        if device is None:
            # Known only from a neighbor's announcement.
            announcers = ", ".join(sorted(set(self.neighbor_only.get(key, ()))))
            if management_state == "failed":
                return HopResult(
                    hop_number=hop_number,
                    device=name,
                    ingress_interface=ingress,
                    egress_interface=egress,
                    link_state="unknown",
                    management_state="failed",
                    status=HOP_FAILED,
                    confidence=self._clamp(CONFIDENCE_DIRECT_EVIDENCE),
                    explanation=(
                        f"{name} is announced by {announcers} but the most "
                        "recent discovery could not reach it — Atlas has "
                        "direct evidence the device did not respond on its "
                        "management path."
                    ),
                    evidence=(f"discovery failure record for {name}",),
                    failure_type=FAILURE_DEVICE_UNREACHABLE,
                )
            missing.append(
                f"{name} has no collected inventory (announced by "
                f"{announcers} only); interface and state validation is not "
                "possible."
            )
            self.unknowns.extend(missing)
            return HopResult(
                hop_number=hop_number,
                device=name,
                ingress_interface=ingress,
                egress_interface=egress,
                link_state="unknown",
                management_state="unknown",
                status=HOP_WARNING,
                confidence=self._clamp(CONFIDENCE_PARTIAL_EVIDENCE),
                explanation=(
                    f"{name} is known only from neighbor announcements "
                    f"({announcers}); Atlas has not discovered it directly, "
                    "so its interfaces and state cannot be validated."
                ),
                evidence=(f"neighbor announcement(s) naming {name}",),
                missing_evidence=tuple(missing),
                failure_type=None,
            )

        evidence.append(self._device_ref(key))
        if management_state == "failed":
            return HopResult(
                hop_number=hop_number,
                device=name,
                ingress_interface=ingress,
                egress_interface=egress,
                link_state="unknown",
                management_state="failed",
                status=HOP_FAILED,
                confidence=self._clamp(CONFIDENCE_DIRECT_EVIDENCE),
                explanation=(
                    f"The most recent discovery could not reach {name} on its "
                    "management address — its collected state is from an "
                    "earlier run and cannot be trusted for this path."
                ),
                evidence=(*evidence, f"discovery failure record for {name}"),
                failure_type=FAILURE_DEVICE_UNREACHABLE,
            )
        if mgmt_note:
            evidence.append(mgmt_note)

        # Interface existence and operational state, per direction.
        states: list[tuple[str, str, str]] = []  # (interface, verdict, detail)
        for interface in (ingress, egress):
            if interface is None:
                continue
            verdict, detail = self._interface_state(key, interface)
            states.append((interface, verdict, detail))
            if verdict == "missing":
                missing.append(
                    f"{name} {interface} is named by neighbor evidence but is "
                    "absent from the collected interface table."
                )
            else:
                evidence.append(f"interface table {name} {interface}: {detail}")

        for interface, verdict, detail in states:
            if verdict == "admin-down":
                return self._interface_failure(
                    hop_number, key, ingress, egress,
                    link_state="administratively-down",
                    failure_type=FAILURE_ADMIN_SHUTDOWN,
                    why=(
                        f"{name} {interface} is administratively shut down "
                        f"({detail}) — an operator disabled it; traffic "
                        "cannot cross this hop until it is re-enabled."
                    ),
                    evidence=tuple(evidence),
                )
            if verdict == "down":
                return self._interface_failure(
                    hop_number, key, ingress, egress,
                    link_state="down",
                    failure_type=FAILURE_INTERFACE_DOWN,
                    why=(
                        f"{name} {interface} is operationally down "
                        f"({detail}) — the link is not passing traffic at "
                        "this hop."
                    ),
                    evidence=tuple(evidence),
                )

        if not states:
            link_state = "n/a"
        elif all(verdict == "up" for _, verdict, _ in states):
            link_state = "up"
        else:
            # Down and admin-down already returned above; what remains is
            # missing or indeterminate evidence.
            link_state = "unknown"
        if missing:
            self.unknowns.extend(missing)
            return HopResult(
                hop_number=hop_number,
                device=name,
                ingress_interface=ingress,
                egress_interface=egress,
                link_state=link_state,
                management_state=management_state,
                status=HOP_WARNING,
                confidence=self._clamp(CONFIDENCE_PARTIAL_EVIDENCE),
                explanation=(
                    f"{name} was reached and validated, but part of its "
                    "interface evidence is missing — the hop cannot be fully "
                    "confirmed."
                ),
                evidence=tuple(evidence),
                missing_evidence=tuple(missing),
                failure_type=None,
            )
        parts = []
        if ingress:
            parts.append(f"ingress {ingress}")
        if egress:
            parts.append(f"egress {egress}")
        described = " and ".join(parts) if parts else "endpoint"
        return HopResult(
            hop_number=hop_number,
            device=name,
            ingress_interface=ingress,
            egress_interface=egress,
            link_state=link_state,
            management_state=management_state,
            status=HOP_PASS,
            confidence=self._clamp(CONFIDENCE_DIRECT_EVIDENCE),
            explanation=(
                f"{name} is discovered and manageable; {described} "
                "interface(s) exist in the collected inventory and report "
                "an operational up state."
                if states
                else f"{name} is discovered and manageable."
            ),
            evidence=tuple(evidence),
            failure_type=None,
        )

    def _interface_failure(
        self,
        hop_number: int,
        key: str,
        ingress: str | None,
        egress: str | None,
        *,
        link_state: str,
        failure_type: str,
        why: str,
        evidence: tuple[str, ...],
    ) -> HopResult:
        name = self._display_name(key)
        if name.casefold() in self.captured_configs:
            evidence = (
                *evidence,
                f"captured running configuration for {name} is available for "
                "review (configs/)",
            )
        return HopResult(
            hop_number=hop_number,
            device=name,
            ingress_interface=ingress,
            egress_interface=egress,
            link_state=link_state,
            management_state=self._management_state(key)[0],
            status=HOP_FAILED,
            confidence=self._clamp(CONFIDENCE_DIRECT_EVIDENCE),
            explanation=why,
            evidence=evidence,
            failure_type=failure_type,
        )

    def _not_evaluated_hop(
        self, hop_number: int, key: str, failure: HopResult
    ) -> HopResult:
        name = self._display_name(key)
        return HopResult(
            hop_number=hop_number,
            device=name,
            ingress_interface=None,
            egress_interface=None,
            link_state="unknown",
            management_state="unknown",
            status=HOP_UNKNOWN,
            confidence=CONFIDENCE_NOT_EVALUATED,
            explanation=(
                f"Not evaluated: the investigation stopped at {failure.device} "
                f"({failure.failure_type}). Whether this hop is healthy is "
                "unknown until the earlier failure is resolved."
            ),
            failure_type=None,
        )

    # -- evidence lookups ---------------------------------------------------------

    def _interface_state(self, key: str, interface: str) -> tuple[str, str]:
        """Return (verdict, detail): up | down | admin-down | unknown | missing."""

        device = self.devices.get(key)
        if device is None:
            return "missing", "no collected inventory"
        wanted = interface.casefold()
        for entry in device.get("interfaces") or ():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("name") or "").casefold() != wanted:
                continue
            status = str(entry.get("status") or "").casefold()
            protocol = str(entry.get("protocol_status") or "").casefold()
            detail = f"{entry.get('status') or 'unknown'}/{entry.get('protocol_status') or 'unknown'}"
            if "administratively" in status:
                return "admin-down", detail
            if status == "down" or protocol == "down":
                return "down", detail
            if status == "up" and protocol in ("up", ""):
                return "up", detail
            return "unknown", detail
        return "missing", "not present in the collected interface table"

    def _management_state(self, key: str) -> tuple[str, str | None]:
        device = self.devices.get(key)
        hostname = self._display_name(key).casefold()
        candidates = {hostname}
        if device is not None and device.get("management_ip"):
            candidates.add(str(device.get("management_ip")).casefold())
        if candidates & self.failed_hosts:
            return "failed", None
        if device is not None and device.get("management_ip"):
            return (
                "reachable",
                f"discovered via management address "
                f"{device.get('management_ip')} this snapshot",
            )
        return "unknown", None

    def _link_interface(self, from_key: str, to_key: str) -> str | None:
        """The interface on ``from_key`` facing ``to_key`` (active preferred)."""

        pair = tuple(sorted((from_key, to_key)))
        records = self.links.get((pair[0], pair[1]), ())
        if not records:
            return None

        def oriented(record: dict) -> str | None:
            if record["a"] == from_key:
                return record["a_interface"]
            return record["b_interface"]

        def is_up(record: dict) -> bool:
            name = oriented(record)
            if name is None:
                return False
            verdict, _ = self._interface_state(from_key, name)
            return verdict == "up"

        ordered = sorted(
            records, key=lambda item: (not is_up(item), str(oriented(item) or ""))
        )
        return oriented(ordered[0])

    # -- terminal results ---------------------------------------------------------

    def _single_device_result(self, key: str) -> PathInvestigationResult:
        hop = self._validate_hop(hop_number=1, key=key, ingress=None, egress=None)
        self._step(
            f"Validate {hop.device}", hop.status, hop.explanation,
            evidence=hop.evidence,
        )
        connected = hop.status in (HOP_PASS, HOP_WARNING)
        return self._finish(
            status=RESULT_CONNECTED if connected else RESULT_FAILED,
            path=(hop.device,),
            hops=(hop,),
            failure_type=None if connected else hop.failure_type,
            failure_summary=None if connected else hop.explanation,
            confidence=hop.confidence,
            recommendations=(
                "Source and destination are the same device; only the device "
                "itself was validated.",
            )
            if connected
            else tuple(self._failure_recommendations(hop)),
        )

    def _failed_walk_result(
        self, path: list[str], hops: list[HopResult], failure: HopResult
    ) -> PathInvestigationResult:
        names = tuple(self._display_name(key) for key in path)
        self._step(
            "Conclusion",
            HOP_FAILED,
            f"Communication stops at {failure.device}: {failure.explanation}",
            evidence=failure.evidence,
        )
        evaluated = [hop for hop in hops if hop.status != HOP_UNKNOWN]
        confidence = min(
            (hop.confidence for hop in evaluated), default=failure.confidence
        )
        return self._finish(
            status=RESULT_FAILED,
            path=names,
            hops=tuple(hops),
            failure_type=failure.failure_type,
            failure_summary=(
                f"Hop {failure.hop_number} ({failure.device}): "
                f"{failure.explanation}"
            ),
            confidence=confidence,
            recommendations=tuple(self._failure_recommendations(failure)),
        )

    def _failure_recommendations(self, failure: HopResult) -> list[str]:
        device = failure.device
        recommendations: list[str] = []
        if failure.failure_type == FAILURE_ADMIN_SHUTDOWN:
            interface = failure.egress_interface or failure.ingress_interface
            recommendations.extend(
                (
                    f"Find out why {device} {interface} was administratively "
                    "shut down before re-enabling it — an operator disabled "
                    "it deliberately.",
                    f"If the shutdown is unexpected, review the captured "
                    f"configuration and recent change history for {device}.",
                )
            )
        elif failure.failure_type == FAILURE_INTERFACE_DOWN:
            interface = failure.egress_interface or failure.ingress_interface
            recommendations.extend(
                (
                    f"Check the physical layer on {device} {interface} and "
                    "its far end: cabling, optics, and the remote interface "
                    "state.",
                    "Re-run discovery after the physical issue is addressed "
                    "to confirm the link recovers.",
                )
            )
        elif failure.failure_type == FAILURE_DEVICE_UNREACHABLE:
            recommendations.extend(
                (
                    f"Verify {device} is powered and its management path is "
                    "intact; the most recent discovery could not reach it.",
                    "Check credentials and reachability for the device, then "
                    "run a fresh discovery.",
                )
            )
        else:
            recommendations.append(
                f"Investigate {device} directly; Atlas's evidence stops here."
            )
        if device.casefold() in self.captured_configs:
            recommendations.append(
                f"A captured running configuration for {device} is available "
                "under configs/ for review."
            )
        return recommendations

    def _no_path_result(
        self, source_key: str, destination_key: str
    ) -> PathInvestigationResult:
        source_name = self._display_name(source_key)
        destination_name = self._display_name(destination_key)
        isolated = not self.adjacency.get(destination_key)
        detail = (
            f"No discovered topology edge connects {source_name} to "
            f"{destination_name}."
        )
        if isolated:
            detail += (
                f" {destination_name} has no discovered links at all — its "
                "neighbors were never observed."
            )
        self._step("Construct path from topology evidence", HOP_FAILED, detail)
        self.unknowns.append(
            "A physical or logical path may exist that discovery has not "
            "observed (CDP/LLDP disabled, an undiscovered intermediate "
            "device, or a boundary/credential limit)."
        )
        return self._finish(
            status=RESULT_UNKNOWN,
            path=(source_name, destination_name),
            hops=(),
            failure_type=FAILURE_UNKNOWN_PATH
            if not isolated
            else FAILURE_DISCOVERY_INCOMPLETE,
            failure_summary=detail,
            confidence=CONFIDENCE_PARTIAL_EVIDENCE,
            recommendations=(
                "Run a fresh discovery with sufficient depth, seeds, and "
                "credentials so intermediate devices are captured.",
                "Verify CDP/LLDP is enabled along the expected path — Atlas "
                "builds paths only from observed neighbor evidence.",
                "If the devices genuinely share no link, the path does not "
                "exist as asked.",
            ),
        )

    def _validate_path_silently(
        self, path: list[str]
    ) -> tuple[tuple[HopResult, ...], HopResult | None]:
        """Validate every hop of one path WITHOUT emitting story steps.

        Returns ``(hops, first_failure)``. Used to assess each candidate of
        a redundant path set before deciding how to narrate the result."""

        hops: list[HopResult] = []
        failure: HopResult | None = None
        for index, key in enumerate(path):
            if failure is not None:
                hops.append(self._not_evaluated_hop(len(hops) + 1, key, failure))
                continue
            ingress = self._link_interface(key, path[index - 1]) if index else None
            egress = (
                self._link_interface(key, path[index + 1])
                if index + 1 < len(path)
                else None
            )
            hop = self._validate_hop(
                hop_number=len(hops) + 1, key=key, ingress=ingress, egress=egress
            )
            hops.append(hop)
            if hop.status == HOP_FAILED:
                failure = hop
        return tuple(hops), failure

    def _redundant_paths_result(
        self, paths: list[list[str]]
    ) -> PathInvestigationResult:
        """Multiple equal-cost paths = redundancy, reported as CONNECTED.

        Every candidate is validated. If at least one path is fully up, the
        endpoints ARE connected (a resilient design) — a strong positive
        result. If some candidates are degraded, that reduced redundancy is
        surfaced. Only when EVERY candidate has a broken hop is it a real
        failure. Atlas still never guesses which single path a flow uses."""

        rendered = [
            " → ".join(self._display_name(key) for key in path) for path in paths
        ]
        source_name = self._display_name(paths[0][0])
        dest_name = self._display_name(paths[0][-1])

        validated = [(path, *self._validate_path_silently(path)) for path in paths]
        up_paths = [item for item in validated if item[2] is None]
        down_paths = [item for item in validated if item[2] is not None]

        self._step(
            "Construct path from topology evidence",
            HOP_PASS if up_paths else HOP_FAILED,
            f"{len(paths)} equal-cost redundant paths exist between "
            f"{source_name} and {dest_name} — a resilient design: "
            + " | ".join(rendered),
            evidence=(self._snapshot_ref(),),
        )

        # No candidate survives validation → genuinely unreachable.
        if not up_paths:
            rep_path, rep_hops, failure = validated[0]
            return self._failed_walk_result(rep_path, list(rep_hops), failure)

        # A representative fully-up path carries the hop-by-hop detail.
        rep_path, rep_hops, _ = up_paths[0]
        for hop in rep_hops:
            self._step(
                f"Validate {hop.device}"
                + (f" (via {hop.ingress_interface})" if hop.ingress_interface else ""),
                hop.status,
                hop.explanation,
                evidence=hop.evidence,
            )
        degraded_note = (
            f" {len(down_paths)} of the {len(paths)} paths are currently "
            "degraded (a hop is down), so redundancy is reduced but "
            "connectivity holds."
            if down_paths
            else ""
        )
        self._step(
            "Conclusion",
            HOP_PASS if not down_paths else HOP_WARNING,
            f"{source_name} reaches {dest_name} over {len(up_paths)} of "
            f"{len(paths)} redundant equal-cost path(s) that pass validation "
            f"— the network has path resilience here.{degraded_note}",
        )
        # Honest, but a footnote — never a failure (PR-043.x path polish).
        self.unknowns.append(
            "Which of the equal-cost paths a given flow uses needs routing / "
            "flow evidence (not collected yet); every candidate path is shown "
            "so none is guessed through."
        )
        recommendations = [
            f"{len(paths)} redundant equal-cost paths provide resilience: "
            f"shutting any single link still leaves {len(paths) - 1}. Verify "
            "each carries the expected capacity.",
            "Collect routing / flow evidence to see which path is active for a "
            "given flow.",
        ]
        if down_paths:
            recommendations.insert(
                0,
                f"Restore the {len(down_paths)} degraded path(s) to recover "
                "full redundancy: " + "; ".join(
                    " → ".join(self._display_name(k) for k in item[0])
                    for item in down_paths
                ),
            )
        return self._finish(
            status=RESULT_CONNECTED,
            path=tuple(self._display_name(key) for key in rep_path),
            hops=rep_hops,
            failure_type=None,
            failure_summary=None,
            confidence=self._overall_confidence(list(rep_hops)),
            recommendations=tuple(recommendations),
            extra_basis={
                "redundant_paths": rendered,
                "redundant_path_count": len(paths),
                "validated_up_paths": len(up_paths),
                "degraded_paths": len(down_paths),
            },
        )

    def _no_evidence_result(self) -> PathInvestigationResult:
        self._step(
            "Load topology evidence",
            HOP_FAILED,
            "No topology snapshot with devices exists for this scope — "
            "there is no evidence to investigate against.",
        )
        return self._finish(
            status=RESULT_UNKNOWN,
            path=(),
            hops=(),
            failure_type=FAILURE_DISCOVERY_INCOMPLETE,
            failure_summary="No topology evidence is available for this scope.",
            confidence=CONFIDENCE_NOT_EVALUATED,
            recommendations=("Run a discovery for this network first.",),
        )

    # -- shared helpers ----------------------------------------------------------

    def _step(
        self,
        title: str,
        status: str,
        detail: str,
        evidence: tuple[str, ...] = (),
    ) -> None:
        self.steps.append(
            InvestigationStep(
                number=len(self.steps) + 1,
                title=title,
                status=status,
                detail=detail,
                evidence=evidence,
            )
        )

    def _clamp(self, value: float) -> float:
        if not self.fresh:
            value -= STALE_PENALTY
        return max(CONFIDENCE_NOT_EVALUATED, min(CONFIDENCE_CAP, value))

    def _overall_confidence(self, hops: list[HopResult]) -> float:
        evaluated = [hop.confidence for hop in hops if hop.status != HOP_UNKNOWN]
        if not evaluated:
            return CONFIDENCE_NOT_EVALUATED
        return min(CONFIDENCE_CAP, min(evaluated))

    def _snapshot_ref(self) -> str:
        assert self.snapshot is not None
        snapshot_id = str(self.snapshot.get("snapshot_id") or "unknown")
        created = str(self.snapshot.get("created_at") or "unknown time")
        short = snapshot_id.split(":")[-1][:12]
        return f"topology snapshot {short} (created {created})"

    def _device_ref(self, key: str) -> str:
        device = self.devices.get(key)
        if device is None:
            announcers = ", ".join(sorted(set(self.neighbor_only.get(key, ()))))
            return (
                f"neighbor announcement(s) from {announcers} naming "
                f"{self._display_name(key)}"
            )
        management = device.get("management_ip")
        suffix = f" at {management}" if management else ""
        return f"device record {device.get('hostname')}{suffix} in the snapshot"

    def _investigation_id(self) -> str:
        snapshot_id = (
            str(self.snapshot.get("snapshot_id")) if self.snapshot else "none"
        )
        content = "|".join(
            (
                snapshot_id,
                self.source.casefold(),
                self.destination.casefold(),
                self.generated_at,
                self.profile_id or "",
            )
        )
        return "path:" + sha256(content.encode("utf-8")).hexdigest()[:16]

    def _finish(
        self,
        *,
        status: str,
        path: tuple[str, ...],
        hops: tuple[HopResult, ...],
        failure_type: str | None,
        failure_summary: str | None,
        confidence: float,
        recommendations: tuple[str, ...],
        extra_basis: dict | None = None,
    ) -> PathInvestigationResult:
        basis: dict = {
            "snapshot_id": str(self.snapshot.get("snapshot_id"))
            if self.snapshot
            else None,
            "snapshot_created_at": str(self.snapshot.get("created_at"))
            if self.snapshot and self.snapshot.get("created_at")
            else None,
            "fresh": self.fresh,
        }
        if extra_basis:
            basis.update(extra_basis)
        # De-duplicate while preserving order.
        seen: set[str] = set()
        unknowns = tuple(
            item for item in self.unknowns if not (item in seen or seen.add(item))
        )
        return PathInvestigationResult(
            investigation_id=self._investigation_id(),
            generated_at=self.generated_at,
            source=self.source,
            destination=self.destination,
            status=status,
            path=path,
            hops=hops,
            steps=tuple(self.steps),
            failure_type=failure_type,
            failure_summary=failure_summary,
            recommendations=recommendations,
            confidence=max(CONFIDENCE_NOT_EVALUATED, min(CONFIDENCE_CAP, confidence)),
            unknowns=unknowns,
            evidence_refs=tuple(self.evidence_refs),
            profile_id=self.profile_id,
            basis=basis,
        )
