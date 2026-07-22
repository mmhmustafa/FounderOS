"""The deterministic prediction pipeline.

    Change Request -> Dependency Resolution -> Critical Path Evaluation
    -> Redundancy Evaluation -> Impact Estimation -> Risk Estimation
    -> Confidence Calculation -> Recommendations

Per-change-type *evaluators* are registered, never hardcoded: registering
an evaluator for a new change type (routing simulation, firewall policy,
Kubernetes CNI, cloud) extends the simulator without touching it. A change
type with no evaluator still predicts honestly — explicit unknowns, low
confidence — rather than failing or guessing.

Inputs are the artifacts existing engines already produce (topology
snapshot, history records, configuration presence); nothing is duplicated.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace as dataclass_replace
from typing import Any

from .change_requests import change_type
from .confidence import assess_confidence
from .critical_paths import affected_critical_paths
from .dependency import (
    DependencyGraph,
    KIND_APPLICATION,
    KIND_SERVICE,
    build_topology_dependency_graph,
    device_node_id,
    interface_node_id,
)
from .impact import BlastRadius, estimate_blast_radius
from .models import (
    Boundary,
    ChangeRequest,
    LIKELIHOOD_EXPECTED,
    LIKELIHOOD_POSSIBLE,
    LIKELIHOOD_PROBABLE,
    Prediction,
    PredictedOutcome,
    SEVERITY_HIGH,
    SEVERITY_LOW,
)
from .planes import (
    ALTERNATE_VERIFIED,
    PLANE_CONTROL,
    PLANE_DATA,
    STATUS_LOST,
    evaluate_planes,
)
from .recommendations import advise
from .redundancy import RedundancyAssessment
from .risk import estimate_risk
from .rollback import estimate_rollback


@dataclass(frozen=True)
class Evaluation:
    """What a change-type evaluator contributes to the pipeline."""

    target_node_id: str | None
    outcomes: tuple[PredictedOutcome, ...]
    unknowns: tuple[str, ...] = ()


Evaluator = Callable[[ChangeRequest, DependencyGraph], Evaluation]

_EVALUATORS: dict[str, Evaluator] = {}


def register_evaluator(change_type_name: str, evaluator: Evaluator) -> None:
    """Extend the simulator with a new change type — no core changes."""

    _EVALUATORS[change_type_name] = evaluator


def registered_evaluators() -> tuple[str, ...]:
    return tuple(sorted(_EVALUATORS))


def predict(
    request: ChangeRequest,
    *,
    snapshot: dict | None,
    generated_at: str,
    boundary: Boundary | None = None,
    graph: DependencyGraph | None = None,
    history_available: bool = False,
    configuration_captured: bool = False,
    fresh: bool = True,
    health_score: int | None = None,
    historically_unstable: bool = False,
    device_sites: Mapping[str, str] | None = None,
    seed_addresses: tuple[str, ...] = (),
    role_evidence: Mapping[str, Any] | None = None,
) -> Prediction:
    """Run the deterministic prediction pipeline for one change request.

    ``graph`` may be injected pre-enriched (service/application nodes from
    future builders); by default it is built from the topology snapshot.
    ``health_score`` (current enterprise intelligence), ``historically_
    unstable`` (target instability from history), and ``device_sites``
    (hostname -> site label) enrich risk and blast radius when available.
    """

    resolved_boundary = boundary or Boundary()
    dependency_graph = graph or build_topology_dependency_graph(snapshot)
    evaluator = _EVALUATORS.get(request.change_type)
    unknowns: list[str] = []
    if evaluator is not None:
        evaluation = evaluator(request, dependency_graph)
    else:
        evaluation = Evaluation(
            target_node_id=(
                device_node_id(request.target_device)
                if dependency_graph.node(device_node_id(request.target_device))
                else None
            ),
            outcomes=(
                PredictedOutcome(
                    category="modeling",
                    description=(
                        f"Change type {request.change_type!r} is not yet "
                        "modeled; Atlas can only reason about the target "
                        "device's topology position."
                    ),
                    likelihood=LIKELIHOOD_POSSIBLE,
                ),
            ),
            unknowns=(
                f"no evaluator registered for change type {request.change_type!r}",
            ),
        )
    unknowns.extend(evaluation.unknowns)

    # Dependency resolution -> impact, critical paths, redundancy.
    if evaluation.target_node_id is not None:
        blast_radius = estimate_blast_radius(
            dependency_graph,
            evaluation.target_node_id,
            target_label=request.subject,
            anchor_node_id=device_node_id(request.target_device),
        )
        critical_paths = affected_critical_paths(
            dependency_graph, evaluation.target_node_id
        )
    else:
        blast_radius = BlastRadius(
            summary=f"{request.subject} is not present in the current topology."
        )
        critical_paths = ()
        unknowns.append(
            f"{request.subject} was not found in the discovered topology"
        )
    if critical_paths:
        # No alternate is KNOWN — and absence cannot be verified from
        # discovery alone, so redundancy is unknown, never assumed.
        redundancy = RedundancyAssessment(
            redundant=None,
            alternate_path_exists=False,
            detail=(
                f"{len(critical_paths)} forwarding path(s) have no known "
                "alternate route; redundancy is unknown, not assumed"
            ),
        )
    elif evaluation.target_node_id is not None and _carries_links(
        dependency_graph, evaluation.target_node_id, request.target_device
    ):
        redundancy = RedundancyAssessment(
            redundant=True,
            alternate_path_exists=True,
            detail=(
                "the changed element carries links, but every device pair "
                "keeps an alternate topology path without it"
            ),
        )
    else:
        redundancy = RedundancyAssessment(
            redundant=None,
            alternate_path_exists=False,
            detail="nothing downstream depends on the changed element",
        )

    # Risk: the worst of impact severity and critical-path breakage.
    severity = SEVERITY_HIGH if critical_paths else blast_radius.severity

    # Unknown dependency layers: honesty about what the graph cannot see.
    unknown_layers = 0
    if not dependency_graph.nodes(KIND_SERVICE):
        unknown_layers += 1
        unknowns.append("service dependencies are not yet modeled")
    if not dependency_graph.nodes(KIND_APPLICATION):
        unknown_layers += 1
        unknowns.append("application dependencies are not yet modeled")

    confidence = assess_confidence(
        topology_available=snapshot is not None or graph is not None,
        fresh=fresh,
        configuration_captured=configuration_captured,
        history_available=history_available,
        evaluator_registered=evaluator is not None,
        unknown_layers=unknown_layers,
    )
    rollback = estimate_rollback(
        request, configuration_captured=configuration_captured
    )

    # Enrich blast radius: affected sites and the projected health impact
    # (the intelligence-engine weights applied to the predicted state).
    touches_links = evaluation.target_node_id is not None and _carries_links(
        dependency_graph, evaluation.target_node_id, request.target_device
    )
    sites = ()
    if device_sites:
        sites = tuple(
            sorted(
                {
                    str(device_sites[name])
                    for name in blast_radius.affected_devices
                    if name in device_sites
                }
            )
        )
    health_impact = -(8 if touches_links else 0) - 6 * len(
        blast_radius.affected_devices
    )
    blast_radius = dataclass_replace(
        blast_radius,
        affected_sites=sites,
        attributes={
            **dict(blast_radius.attributes),
            "estimated_health_impact": health_impact,
        },
    )

    # Plane-aware impact (PR-036C): management / control / data /
    # observability, evaluated from the device's discovered evidence.
    planes: tuple = ()
    management_lost = False
    management_alternate_verified: bool | None = None
    management_detail = ""
    gateway_lost = False
    control_lost = False
    if request.target_object and isinstance(snapshot, dict):
        device_entry = next(
            (
                entry
                for entry in snapshot.get("devices") or ()
                if isinstance(entry, dict)
                and str(entry.get("hostname") or "").casefold()
                == request.target_device.casefold()
            ),
            None,
        )
        if device_entry is not None:
            planes, management = evaluate_planes(
                device_entry=device_entry,
                target_interface=request.target_object,
                seed_addresses=seed_addresses,
                role_evidence=role_evidence,
                isolated_devices=blast_radius.affected_devices,
                fresh=fresh,
            )
            management_lost = management.owns_management_address
            management_alternate_verified = (
                management.alternate_status == ALTERNATE_VERIFIED
            )
            management_detail = management.alternate_detail
            gateway_lost = any(
                plane.plane == PLANE_DATA
                and plane.status == STATUS_LOST
                and bool((role_evidence or {}).get("gateway"))
                for plane in planes
            )
            control_lost = any(
                plane.plane == PLANE_CONTROL and plane.status == STATUS_LOST
                for plane in planes
            )
            for plane in planes:
                for missing in plane.missing_evidence:
                    unknowns.append(missing)

    risk = estimate_risk(
        critical_path_count=len(critical_paths),
        affected_device_count=len(blast_radius.affected_devices),
        carries_links=touches_links,
        redundancy_verified=redundancy.redundant,
        health_score=health_score,
        historically_unstable=historically_unstable,
        confidence_band=confidence.band,
        management_lost=management_lost,
        management_alternate_verified=management_alternate_verified,
        gateway_lost=gateway_lost,
        control_lost=control_lost,
    )
    advice = advise(
        risk=risk,
        blast_radius=blast_radius,
        critical_paths=critical_paths,
        redundancy=redundancy,
        rollback=rollback,
        subject=request.subject,
        target_known=evaluation.target_node_id is not None,
        touches_links=touches_links,
        management_lost=management_lost,
        management_alternate_verified=management_alternate_verified,
        management_detail=management_detail,
    )
    explanation = _explain(
        request=request,
        outcomes=evaluation.outcomes,
        blast_radius=blast_radius,
        critical_paths=critical_paths,
        redundancy=redundancy,
        risk=risk,
        confidence=confidence,
        snapshot=snapshot,
        history_available=history_available,
    )
    if planes:
        explanation = explanation + tuple(
            f"{plane.plane.title()} plane: {plane.status.replace('_', ' ')} "
            f"({plane.confidence_percent}% confidence) — {plane.explanation}"
            for plane in planes
        )
    spec = change_type(request.change_type)
    return Prediction(
        prediction_id=f"prediction:{request.request_id}",
        generated_at=generated_at,
        change_request=request,
        boundary=resolved_boundary,
        outcomes=evaluation.outcomes,
        blast_radius=blast_radius,
        critical_paths=critical_paths,
        redundancy=redundancy,
        rollback=rollback,
        severity=severity if evaluation.target_node_id is not None else SEVERITY_LOW,
        confidence=confidence,
        recommendations=advice.lines(),
        unknowns=tuple(dict.fromkeys(unknowns)),  # deterministic de-dupe
        evidence_refs=_evidence_refs(snapshot, history_available, health_score),
        basis={
            "change_category": spec.category if spec else "unregistered",
            "snapshot_id": (
                str(snapshot.get("snapshot_id")) if isinstance(snapshot, dict) else None
            ),
            "graph_nodes": len(dependency_graph.nodes()),
            "graph_edges": len(dependency_graph.edges()),
        },
        risk=risk,
        advice=advice,
        explanation=explanation,
        planes=planes,
    )


def _evidence_refs(
    snapshot: dict | None, history_available: bool, health_score: int | None
) -> tuple[str, ...]:
    refs: list[str] = []
    if snapshot is not None:
        refs.append("topology_snapshot.json")
        refs.append("state_change_report.json")
    if history_available:
        refs.append("discovery history")
    if health_score is not None:
        refs.append("intelligence_report.json")
    return tuple(refs)


def _explain(
    *,
    request: ChangeRequest,
    outcomes,
    blast_radius,
    critical_paths,
    redundancy,
    risk,
    confidence,
    snapshot,
    history_available: bool,
) -> tuple[str, ...]:
    """Human-readable reasoning; every line traceable to the evidence."""

    lines: list[str] = []
    for outcome in outcomes:
        lines.append(f"{outcome.description} ({outcome.likelihood})")
    if blast_radius.affected_devices:
        lines.append(
            f"{', '.join(blast_radius.affected_devices)} would lose "
            "connectivity [topology snapshot]."
        )
    if blast_radius.affected_sites:
        lines.append(
            "Affected site(s): " + ", ".join(blast_radius.affected_sites) + "."
        )
    if critical_paths:
        lines.append(
            f"{len(critical_paths)} known forwarding path(s) have no "
            "alternate route without this element [topology snapshot]."
        )
    lines.append(f"Redundancy: {redundancy.detail}.")
    impact = blast_radius.attributes.get("estimated_health_impact")
    if isinstance(impact, int) and impact < 0:
        lines.append(
            f"Projected enterprise health impact: {impact} point(s) "
            "[intelligence weights]."
        )
    lines.append(
        f"Risk {risk.level} (score {risk.score}) from "
        f"{len(risk.factors)} documented factor(s)."
    )
    evidence_bits = []
    if snapshot is not None:
        evidence_bits.append("topology")
    evidence_bits.append("operational state")
    if history_available:
        evidence_bits.append("discovery history")
    lines.append(
        f"Confidence {confidence.band} ({confidence.percent}%) based on "
        + ", ".join(evidence_bits)
        + "."
    )
    return tuple(lines)


def _carries_links(
    graph: DependencyGraph, node_id: str, own_device: str
) -> bool:
    """Whether the changed element connects to anything beyond its device."""

    for neighbor_id in graph.neighbors(node_id):
        neighbor = graph.node(neighbor_id)
        if neighbor is None:
            continue
        owner = neighbor.device or neighbor.name
        if owner and owner.casefold() != own_device.casefold():
            return True
    return False


# -- built-in evaluators (the first working slice of the architecture) --------


def _evaluate_shutdown_interface(
    request: ChangeRequest, graph: DependencyGraph
) -> Evaluation:
    interface = request.target_object or "unknown"
    node_id = interface_node_id(request.target_device, interface)
    if graph.node(node_id) is None:
        return Evaluation(
            target_node_id=None,
            outcomes=(
                PredictedOutcome(
                    category="connectivity",
                    description=(
                        f"{interface} on {request.target_device} is not in "
                        "the discovered topology; impact cannot be traced."
                    ),
                    likelihood=LIKELIHOOD_POSSIBLE,
                ),
            ),
            unknowns=(
                f"{request.target_device} {interface} not present in the "
                "current topology snapshot",
            ),
        )
    adjacent: list[str] = []
    for neighbor_id in graph.neighbors(node_id):
        neighbor = graph.node(neighbor_id)
        if neighbor is None:
            continue
        owner = neighbor.device or neighbor.name
        if owner and owner.casefold() != request.target_device.casefold():
            if owner not in adjacent:
                adjacent.append(owner)
    outcomes = [
        PredictedOutcome(
            category="interface",
            description=(
                f"{interface} on {request.target_device} goes "
                "administratively down; its line protocol drops."
            ),
            likelihood=LIKELIHOOD_EXPECTED,
            evidence=(node_id,),
        )
    ]
    if adjacent:
        outcomes.append(
            PredictedOutcome(
                category="connectivity",
                description=(
                    f"The link toward {', '.join(adjacent[:3])} is lost; "
                    "traffic through it must reroute or fail."
                ),
                likelihood=LIKELIHOOD_EXPECTED,
                evidence=(node_id,),
            )
        )
        outcomes.append(
            PredictedOutcome(
                category="topology",
                description=(
                    "Devices reachable only through this link disappear from "
                    "the next discovery."
                ),
                likelihood=LIKELIHOOD_PROBABLE,
                evidence=(node_id,),
            )
        )
    return Evaluation(target_node_id=node_id, outcomes=tuple(outcomes))


def _evaluate_reboot_device(
    request: ChangeRequest, graph: DependencyGraph
) -> Evaluation:
    node_id = device_node_id(request.target_device)
    if graph.node(node_id) is None:
        return Evaluation(
            target_node_id=None,
            outcomes=(
                PredictedOutcome(
                    category="platform",
                    description=(
                        f"{request.target_device} is not in the discovered "
                        "topology; impact cannot be traced."
                    ),
                    likelihood=LIKELIHOOD_POSSIBLE,
                ),
            ),
            unknowns=(
                f"{request.target_device} not present in the current "
                "topology snapshot",
            ),
        )
    return Evaluation(
        target_node_id=node_id,
        outcomes=(
            PredictedOutcome(
                category="platform",
                description=(
                    f"{request.target_device} is unavailable for the "
                    "duration of the reload."
                ),
                likelihood=LIKELIHOOD_EXPECTED,
                evidence=(node_id,),
            ),
            PredictedOutcome(
                category="connectivity",
                description=(
                    "Every link on the device flaps; traffic through it "
                    "must reroute or wait."
                ),
                likelihood=LIKELIHOOD_EXPECTED,
                evidence=(node_id,),
            ),
        ),
    )


def _evaluate_shutdown_device(
    request: ChangeRequest, graph: DependencyGraph
) -> Evaluation:
    """A power-off has the SAME blast radius as a reboot — the device is off
    the network and everything depending on it is affected — so it reuses
    the reboot topology reasoning. What differs is duration: a reboot comes
    back on its own, a shutdown stays down until someone powers it on, so
    the outage is open-ended, not "for the duration of the reload".
    """

    node_id = device_node_id(request.target_device)
    if graph.node(node_id) is None:
        return Evaluation(
            target_node_id=None,
            outcomes=(
                PredictedOutcome(
                    category="platform",
                    description=(
                        f"{request.target_device} is not in the discovered "
                        "topology; impact cannot be traced."
                    ),
                    likelihood=LIKELIHOOD_POSSIBLE,
                ),
            ),
            unknowns=(
                f"{request.target_device} not present in the current "
                "topology snapshot",
            ),
        )
    return Evaluation(
        target_node_id=node_id,
        outcomes=(
            PredictedOutcome(
                category="platform",
                description=(
                    f"{request.target_device} goes offline and stays down "
                    "until it is powered back on — there is no automatic "
                    "recovery."
                ),
                likelihood=LIKELIHOOD_EXPECTED,
                evidence=(node_id,),
            ),
            PredictedOutcome(
                category="connectivity",
                description=(
                    "Every link on the device goes down; traffic through it "
                    "must reroute for the duration of the outage."
                ),
                likelihood=LIKELIHOOD_EXPECTED,
                evidence=(node_id,),
            ),
        ),
    )


register_evaluator("shutdown-interface", _evaluate_shutdown_interface)
register_evaluator("reboot-device", _evaluate_reboot_device)
register_evaluator("shutdown-device", _evaluate_shutdown_device)
