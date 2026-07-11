"""Compass models: plans, planned changes, analyses, and assessments.

Compass is NOT an approval workflow — it is a deterministic
change-planning engine. A ``ChangePlan`` holds many planned changes for
one maintenance window; analysis produces per-change evidence (via the
prediction engine), an evidence-based dependency set, a recommended
execution order with the WHY for every position, warned-never-blocking
conflicts, and a plan-level risk summary. Unknowns remain unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from founderos_atlas.prediction import ChangeTypeSpec, register_change_type
from founderos_atlas.root_cause.confidence import band as confidence_band


COMPASS_SCHEMA_VERSION = "1.0.0"

PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_ANALYSED = "analysed"

# The Compass change vocabulary. Each type maps onto the prediction
# engine's open registry; unmodeled types predict honestly (low
# confidence, explicit unknowns) rather than pretending.
#   compass type          -> prediction change type
CHANGE_TYPES: dict[str, dict[str, str]] = {
    "shutdown-interface": {
        "label": "Shutdown interface",
        "prediction_type": "shutdown-interface",
    },
    "enable-interface": {
        "label": "Bring interface up",
        "prediction_type": "enable-interface",
    },
    "configuration-change": {
        "label": "Configuration change",
        "prediction_type": "modify-configuration",
    },
    # An IOS upgrade deterministically includes a reload, so its impact
    # is predicted through the modeled reboot semantics — evidence, not
    # invention. The step keeps its own label.
    "ios-upgrade": {
        "label": "IOS upgrade",
        "prediction_type": "reboot-device",
    },
    "acl-change": {
        "label": "ACL change",
        "prediction_type": "modify-acl",
    },
    "vlan-change": {
        "label": "VLAN change",
        "prediction_type": "modify-vlan",
    },
    "static-route-change": {
        "label": "Static route change",
        "prediction_type": "modify-static-route",
    },
}

# Register the prediction-side vocabulary Compass introduces. Future
# change types plug in by adding a CHANGE_TYPES entry + registration.
for _name, _category, _reversible, _description in (
    ("enable-interface", "interface", True, "Administratively enable an interface."),
    ("modify-configuration", "configuration", True, "Apply a configuration change."),
    ("modify-vlan", "switching", True, "Change VLAN configuration."),
    ("modify-static-route", "routing", True, "Change a static route."),
):
    register_change_type(
        ChangeTypeSpec(
            name=_name,
            category=_category,
            reversible_by_default=_reversible,
            description=_description,
        )
    )


@dataclass(frozen=True)
class PlannedChange:
    """One engineer-planned change inside a maintenance window."""

    change_id: str
    device: str
    change_type: str
    reason: str = ""
    interface: str | None = None
    estimated_duration_minutes: int | None = None
    rollback_available: bool | None = None  # None = honestly unknown
    notes: str = ""

    def __post_init__(self) -> None:
        if self.change_type not in CHANGE_TYPES:
            raise ValueError(f"unknown compass change type: {self.change_type}")
        for name in ("change_id", "device"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")

    @property
    def label(self) -> str:
        return CHANGE_TYPES[self.change_type]["label"]

    @property
    def subject(self) -> str:
        return f"{self.device} {self.interface}".strip() if self.interface else self.device

    @property
    def title(self) -> str:
        return f"{self.label} — {self.subject}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "device": self.device,
            "interface": self.interface,
            "change_type": self.change_type,
            "label": self.label,
            "reason": self.reason,
            "estimated_duration_minutes": self.estimated_duration_minutes,
            "rollback_available": self.rollback_available,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "PlannedChange":
        return cls(
            change_id=value["change_id"],
            device=value["device"],
            interface=value.get("interface"),
            change_type=value["change_type"],
            reason=value.get("reason") or "",
            estimated_duration_minutes=value.get("estimated_duration_minutes"),
            rollback_available=value.get("rollback_available"),
            notes=value.get("notes") or "",
        )


@dataclass(frozen=True)
class ChangePlan:
    """One maintenance window's worth of planned changes."""

    plan_id: str
    title: str
    maintenance_window: str
    engineer: str
    created_at: str
    updated_at: str
    cab_reference: str | None = None
    scope: str = "all"  # the enterprise scope (UNITY)
    status: str = PLAN_STATUS_DRAFT
    changes: tuple[PlannedChange, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "maintenance_window": self.maintenance_window,
            "engineer": self.engineer,
            "cab_reference": self.cab_reference,
            "scope": self.scope,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "changes": [change.to_dict() for change in self.changes],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "ChangePlan":
        return cls(
            plan_id=value["plan_id"],
            title=value["title"],
            maintenance_window=value.get("maintenance_window") or "",
            engineer=value.get("engineer") or "",
            cab_reference=value.get("cab_reference"),
            scope=value.get("scope") or "all",
            status=value.get("status") or PLAN_STATUS_DRAFT,
            created_at=value["created_at"],
            updated_at=value["updated_at"],
            changes=tuple(
                PlannedChange.from_dict(item) for item in value.get("changes") or ()
            ),
        )


@dataclass(frozen=True)
class Dependency:
    """A must run before B — only ever derived from cited evidence."""

    before_change_id: str
    after_change_id: str
    reason: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_change_id": self.before_change_id,
            "after_change_id": self.after_change_id,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class Conflict:
    """An obvious clash between planned changes. Warned, never blocking."""

    kind: str
    change_ids: tuple[str, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "change_ids": list(self.change_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ChangeAnalysis:
    """Everything the evidence says about one planned change."""

    change_id: str
    risk_level: str
    risk_score: int
    confidence: float
    blast_devices: tuple[str, ...]
    health_impact: int | None
    rollback_reversible: bool | None
    unknowns: tuple[str, ...]
    evidence: tuple[str, ...]
    prediction_modeled: bool

    @property
    def confidence_band(self) -> str:
        return confidence_band(self.confidence)

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "confidence": round(self.confidence, 4),
            "confidence_percent": self.confidence_percent,
            "confidence_band": self.confidence_band,
            "blast_devices": list(self.blast_devices),
            "health_impact": self.health_impact,
            "rollback_reversible": self.rollback_reversible,
            "unknowns": list(self.unknowns),
            "evidence": list(self.evidence),
            "prediction_modeled": self.prediction_modeled,
        }


@dataclass(frozen=True)
class PlanStep:
    """One position in the recommended execution order, with its WHY."""

    order: int
    change_id: str
    title: str
    reason: str
    risk_level: str
    confidence_percent: int
    confidence_band: str
    evidence: tuple[str, ...]
    separate_window: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "change_id": self.change_id,
            "title": self.title,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "confidence_percent": self.confidence_percent,
            "confidence_band": self.confidence_band,
            "evidence": list(self.evidence),
            "separate_window": self.separate_window,
        }


@dataclass(frozen=True)
class RiskSummary:
    overall_risk: str
    highest_risk_change_id: str | None
    highest_risk_title: str | None
    largest_blast_change_id: str | None
    largest_blast_title: str | None
    largest_blast_device_count: int
    total_devices_impacted: int
    impacted_devices: tuple[str, ...]
    rollback_covered: int
    rollback_missing: int
    rollback_unknown: int
    estimated_total_minutes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_risk": self.overall_risk,
            "highest_risk_change_id": self.highest_risk_change_id,
            "highest_risk_title": self.highest_risk_title,
            "largest_blast_change_id": self.largest_blast_change_id,
            "largest_blast_title": self.largest_blast_title,
            "largest_blast_device_count": self.largest_blast_device_count,
            "total_devices_impacted": self.total_devices_impacted,
            "impacted_devices": list(self.impacted_devices),
            "rollback_covered": self.rollback_covered,
            "rollback_missing": self.rollback_missing,
            "rollback_unknown": self.rollback_unknown,
            "estimated_total_minutes": self.estimated_total_minutes,
        }


@dataclass(frozen=True)
class PlanAssessment:
    """The complete deterministic answer for one plan."""

    plan_id: str
    generated_at: str
    steps: tuple[PlanStep, ...]
    analyses: tuple[ChangeAnalysis, ...]
    dependencies: tuple[Dependency, ...]
    conflicts: tuple[Conflict, ...]
    risk: RiskSummary
    unknowns: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    basis: dict[str, Any] = field(default_factory=dict)

    def analysis_for(self, change_id: str) -> ChangeAnalysis | None:
        for analysis in self.analyses:
            if analysis.change_id == change_id:
                return analysis
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMPASS_SCHEMA_VERSION,
            "generated_by": "founderos atlas compass",
            "plan_id": self.plan_id,
            "generated_at": self.generated_at,
            "steps": [step.to_dict() for step in self.steps],
            "analyses": [analysis.to_dict() for analysis in self.analyses],
            "dependencies": [item.to_dict() for item in self.dependencies],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "risk": self.risk.to_dict(),
            "unknowns": list(self.unknowns),
            "evidence_refs": list(self.evidence_refs),
            "basis": dict(self.basis),
        }
