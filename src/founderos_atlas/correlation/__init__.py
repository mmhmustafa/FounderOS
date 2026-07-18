"""Atlas Evidence Correlation (PR-043.7, FUSION).

Drivers collect facts. Normalization creates canonical observations.
Evidence Correlation creates Enterprise Knowledge. Topology is generated
from Enterprise Knowledge.
"""

from .engine import EvidenceCorrelationEngine, build_ownership_index
from .metadata import correlation_metadata
from .models import (
    AddressClaim,
    AddressOwnershipIndex,
    CONFIDENCE_CAP,
    CorrelatedRelationship,
    CorrelationResult,
    EVIDENCE_KINDS,
    OwnershipConflict,
    RELATIONSHIP_TYPES,
    RelationshipEvidence,
    REL_BGP,
    REL_INFERRED,
    REL_LAYER2,
    REL_LAYER3,
    REL_OSPF,
    REL_STATIC,
    REL_UNKNOWN,
    REL_VERIFIED_PHYSICAL,
    REL_VERIFIED_ROUTED,
    UnresolvedObservation,
)

__all__ = [
    "AddressClaim",
    "AddressOwnershipIndex",
    "CONFIDENCE_CAP",
    "CorrelatedRelationship",
    "CorrelationResult",
    "EVIDENCE_KINDS",
    "EvidenceCorrelationEngine",
    "OwnershipConflict",
    "correlation_metadata",
    "RELATIONSHIP_TYPES",
    "RelationshipEvidence",
    "REL_BGP",
    "REL_INFERRED",
    "REL_LAYER2",
    "REL_LAYER3",
    "REL_OSPF",
    "REL_STATIC",
    "REL_UNKNOWN",
    "REL_VERIFIED_PHYSICAL",
    "REL_VERIFIED_ROUTED",
    "UnresolvedObservation",
    "build_ownership_index",
]
