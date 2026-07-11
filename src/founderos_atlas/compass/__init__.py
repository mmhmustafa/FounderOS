"""Atlas Compass (PR-039): the deterministic change-planning engine.

Prediction answers *what happens if I make ONE change*; Compass plans
MANY: given a maintenance window full of planned changes, it analyses
every change through the existing prediction engine, derives
dependencies from cited evidence only (never invented), recommends a
deterministic execution order with the WHY for every position, warns —
never blocks — about conflicts, and summarizes plan risk, blast radius,
rollback coverage, and known unknowns.

Compass is an advisor, not an approval workflow. The engineer remains
in control.
"""

from .engine import (
    analyse_plan,
    detect_conflicts,
    detect_dependencies,
    estimate_plan_risk,
    recommend_order,
)
from .models import (
    CHANGE_TYPES,
    ChangeAnalysis,
    ChangePlan,
    Conflict,
    Dependency,
    PLAN_STATUS_ANALYSED,
    PLAN_STATUS_DRAFT,
    PlanAssessment,
    PlannedChange,
    PlanStep,
    RiskSummary,
)
from .service import (
    PlanRepository,
    add_change,
    analyse_plan_for_workspace,
    compass_dir,
    create_plan,
    remove_change,
)

__all__ = [
    "CHANGE_TYPES",
    "ChangeAnalysis",
    "ChangePlan",
    "Conflict",
    "Dependency",
    "PLAN_STATUS_ANALYSED",
    "PLAN_STATUS_DRAFT",
    "PlanAssessment",
    "PlanRepository",
    "PlanStep",
    "PlannedChange",
    "RiskSummary",
    "add_change",
    "analyse_plan",
    "analyse_plan_for_workspace",
    "compass_dir",
    "create_plan",
    "detect_conflicts",
    "detect_dependencies",
    "estimate_plan_risk",
    "recommend_order",
    "remove_change",
]
