"""Predictive Change Intelligence (PR-036A — architecture milestone).

Atlas evolves Observe -> Understand -> Reason -> **Predict** -> Advise.
This package is the deterministic foundation future prediction engines
build on: first-class ChangeRequest / Boundary / Dependency / Critical
Path / Blast Radius / Redundancy / Rollback / Prediction models, an open
change-type registry, an extensible per-change-type evaluator registry,
and the pipeline

    Change Request -> Dependency Resolution -> Critical Paths ->
    Redundancy -> Impact -> Risk -> Confidence -> Recommendations

seeded with honest first evaluators (interface shutdown, device reboot)
over the existing topology evidence. No AI, no LLM, no guessing:
prediction is deterministic; unknowns are stated, confidence is a
documented calculation that never reaches 100%.
"""

from .change_requests import (
    ChangeTypeSpec,
    change_type,
    known_change_types,
    register_change_type,
)
from .confidence import assess_confidence
from .critical_paths import CriticalPath, affected_critical_paths
from .dependency import (
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    build_topology_dependency_graph,
    device_node_id,
    interface_node_id,
)
from .impact import BlastRadius, estimate_blast_radius
from .interfaces import resolve_interface
from .models import (
    Boundary,
    ChangeRequest,
    ConfidenceAssessment,
    ConfidenceFactor,
    Prediction,
    PredictedOutcome,
)
from .recommendations import Advice, advise
from .redundancy import RedundancyAssessment, assess_redundancy
from .risk import RiskAssessment, RiskFactor, estimate_risk
from .rollback import RollbackEstimate, estimate_rollback
from .service import (
    predict_change,
    render_prediction_json,
    render_prediction_markdown,
)
from .simulator import (
    Evaluation,
    predict,
    register_evaluator,
    registered_evaluators,
)

__all__ = [
    "Advice",
    "BlastRadius",
    "Boundary",
    "ChangeRequest",
    "ChangeTypeSpec",
    "ConfidenceAssessment",
    "ConfidenceFactor",
    "CriticalPath",
    "DependencyEdge",
    "DependencyGraph",
    "DependencyNode",
    "Evaluation",
    "Prediction",
    "PredictedOutcome",
    "RedundancyAssessment",
    "RiskAssessment",
    "RiskFactor",
    "RollbackEstimate",
    "advise",
    "affected_critical_paths",
    "assess_confidence",
    "assess_redundancy",
    "build_topology_dependency_graph",
    "change_type",
    "device_node_id",
    "estimate_blast_radius",
    "estimate_rollback",
    "interface_node_id",
    "estimate_risk",
    "known_change_types",
    "predict",
    "predict_change",
    "register_change_type",
    "register_evaluator",
    "registered_evaluators",
    "render_prediction_json",
    "render_prediction_markdown",
    "resolve_interface",
]
