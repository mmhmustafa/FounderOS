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
    SITE_TYPE_BRANCH,
    SITE_TYPE_CAMPUS,
    SITE_TYPE_CLOUD,
    SITE_TYPE_CUSTOM,
    SITE_TYPE_DATACENTER,
    SITE_TYPE_INTERNET,
    SITE_TYPE_SITE,
    SITE_TYPE_TRANSIT,
    SITE_TYPE_UNCLASSIFIED,
    SITE_TYPE_WAN,
    SITE_TYPES,
    SITE_TYPES_PREMISES,
    Site,
    SiteAssignment,
    SiteCatalog,
    SiteEvidence,
)
from .overrides import (
    SiteOverride,
    SiteOverrideCatalog,
    SiteOverrideConflictError,
    SiteOverrideEvent,
    SiteOverrideRepository,
    device_identity_keys,
)
from .repository import SiteCatalogRepository

__all__ = [
    "ASSIGNMENT_AMBIGUOUS",
    "ASSIGNMENT_ASSIGNED",
    "ASSIGNMENT_UNKNOWN",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "SITE_TYPE_BRANCH",
    "SITE_TYPE_CAMPUS",
    "SITE_TYPE_CLOUD",
    "SITE_TYPE_CUSTOM",
    "SITE_TYPE_DATACENTER",
    "SITE_TYPE_INTERNET",
    "SITE_TYPE_SITE",
    "SITE_TYPE_TRANSIT",
    "SITE_TYPE_UNCLASSIFIED",
    "SITE_TYPE_WAN",
    "SITE_TYPES",
    "SITE_TYPES_PREMISES",
    "Site",
    "SiteAssignment",
    "SiteCatalog",
    "SiteCatalogRepository",
    "SiteEvidence",
    "SiteInferenceEngine",
    "SiteOverride",
    "SiteOverrideCatalog",
    "SiteOverrideConflictError",
    "SiteOverrideEvent",
    "SiteOverrideRepository",
    "device_identity_keys",
]
