"""Enterprise topology: many profiles, one evidence-based network view.

A discovery profile is an entry point, not a site or ownership boundary.
Multiple profiles contribute observations to one enterprise topology in
which canonical device identity is global — but merging across profiles is
strictly evidence-based: strong identifiers (serial numbers) always merge;
hostname+IP agreement merges only when no administrative-domain conflict
exists; hostname alone or IP alone never merges, because real enterprises
reuse both. Every device retains provenance: which profile and which
discovery run observed it. The view is pure aggregation of each profile's
latest state — absence from one profile's run can never mark another
profile's device as removed.
"""

from .knowledge import (
    DiscoveryStatistics,
    EnterpriseKnowledge,
    classify_discovery_visits,
)
from .network_identity import (
    DUPLICATE_THRESHOLD,
    DuplicateCandidate,
    Network,
    NetworkFingerprint,
    NetworkResolution,
    ObservationPoint,
    SimilarityResult,
    compare_fingerprints,
    detect_duplicate_networks,
    fingerprint_snapshot,
    resolve_networks,
)
from .models import (
    DeviceObservation,
    EnterpriseDevice,
    EnterpriseTopology,
)
from .view import (
    ScopeContribution,
    build_enterprise_topology,
    build_enterprise_view,
    gather_scope_contributions,
)

__all__ = [
    "DUPLICATE_THRESHOLD",
    "DeviceObservation",
    "DiscoveryStatistics",
    "DuplicateCandidate",
    "EnterpriseDevice",
    "EnterpriseKnowledge",
    "EnterpriseTopology",
    "Network",
    "NetworkFingerprint",
    "NetworkResolution",
    "ObservationPoint",
    "ScopeContribution",
    "SimilarityResult",
    "build_enterprise_topology",
    "build_enterprise_view",
    "classify_discovery_visits",
    "compare_fingerprints",
    "detect_duplicate_networks",
    "fingerprint_snapshot",
    "gather_scope_contributions",
    "resolve_networks",
]
