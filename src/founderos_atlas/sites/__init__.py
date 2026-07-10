"""Evidence-based site model and inference foundation.

A site is a physical or administrative location — never "a subnet". Site
assignment weighs multiple independent signals (explicit user assignment,
hostname conventions, seed-origin hints, network ranges as corroboration
only) and honestly reports Unknown or Ambiguous instead of inventing a
classification. Every assignment carries its confidence and the evidence
that produced it.
"""

from .inference import SiteInferenceEngine
from .models import (
    ASSIGNMENT_AMBIGUOUS,
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_UNKNOWN,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Site,
    SiteAssignment,
    SiteCatalog,
    SiteEvidence,
)
from .repository import SiteCatalogRepository

__all__ = [
    "ASSIGNMENT_AMBIGUOUS",
    "ASSIGNMENT_ASSIGNED",
    "ASSIGNMENT_UNKNOWN",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "Site",
    "SiteAssignment",
    "SiteCatalog",
    "SiteCatalogRepository",
    "SiteEvidence",
    "SiteInferenceEngine",
]
