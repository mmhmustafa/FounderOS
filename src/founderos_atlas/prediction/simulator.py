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

from collections.abc import Callable
from dataclasses import dataclass

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
from .recommendations import recommend
from .redundancy import RedundancyAssessment
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
) -> Prediction:
    """Run the deterministic prediction pipeline for one change request.

    ``graph`` may be injected pre-enriched (service/application nodes from
    future builders); by default it is built from the topology snapshot.
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
        redundancy = RedundancyAssessment(
            redundant=False,
            alternate_path_exists=False,
            detail=(
                f"{len(critical_paths)} forwarding path(s) have no alternate "
                "route without the changed element"
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
    recommendations = recommend(
        blast_radius=blast_radius,
        critical_paths=critical_paths,
        redundancy=redundancy,
        rollback=rollback,
        subject=request.subject,
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
        recommendations=recommendations,
        unknowns=tuple(dict.fromkeys(unknowns)),  # deterministic de-dupe
        evidence_refs=("topology_snapshot.json",) if snapshot is not None else (),
        basis={
            "change_category": spec.category if spec else "unregistered",
            "snapshot_id": (
                str(snapshot.get("snapshot_id")) if isinstance(snapshot, dict) else None
            ),
            "graph_nodes": len(dependency_graph.nodes()),
            "graph_edges": len(dependency_graph.edges()),
        },
    )


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


register_evaluator("shutdown-interface", _evaluate_shutdown_interface)
register_evaluator("reboot-device", _evaluate_reboot_device)
