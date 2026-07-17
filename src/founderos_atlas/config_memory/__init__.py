"""Configuration Memory (PR-044, MEMORY).

Discovery tells Atlas what exists today. Configuration Memory tells Atlas
what existed yesterday — every successful collection becomes a durable,
versioned, content-addressed historical observation, with structured
knowledge extracted from it.

    collect → snapshot → content-addressed store → versions → history
                                                  ↘ facts → semantic events
                                                            ↘ timeline

Content-addressing means identical configuration is stored once and
re-observed, never duplicated. Configuration TEXT lives only in the local
blob store (sensitive, like the existing ``configs/`` artifacts); every
model, event, diff, and report here is masked or provenance-only, so no
secret reaches a report, API, or console.
"""

from .extract import (
    BgpNeighborFact,
    ConfigFacts,
    HsrpGroupFact,
    InterfaceFact,
    OspfInterfaceFact,
    extract_facts,
)
from .models import (
    CONFIG_MEMORY_SCHEMA_VERSION,
    ConfigObservation,
    ConfigSnapshot,
    ConfigVersion,
    DeviceConfigHistory,
    RECORD_NEW_DEVICE,
    RECORD_NEW_VERSION,
    RECORD_UNCHANGED,
    RecordOutcome,
    TimelineEvent,
    config_version_id,
)
from .policy import (
    COLLECTION_POLICIES,
    CollectionDecision,
    DEFAULT_SCHEDULE_HOURS,
    POLICY_ALWAYS,
    POLICY_DISABLED,
    POLICY_DISCOVERY_ONLY,
    POLICY_MANUAL,
    POLICY_SCHEDULED,
    decide_collection,
    normalize_policy,
)
from .semantic import (
    SemanticEvent,
    highest_severity,
    semantic_diff,
    semantic_diff_text,
    summarize_events,
)
from .store import ConfigMemoryStore, config_sha256
from .textual import ConfigLine, ConfigView, DiffLine, TextDiff, config_view, text_diff
from .timeline import device_timeline, enterprise_timeline, group_by_day

__all__ = [
    "BgpNeighborFact",
    "COLLECTION_POLICIES",
    "CONFIG_MEMORY_SCHEMA_VERSION",
    "CollectionDecision",
    "ConfigFacts",
    "ConfigMemoryStore",
    "ConfigObservation",
    "ConfigSnapshot",
    "ConfigVersion",
    "DEFAULT_SCHEDULE_HOURS",
    "DeviceConfigHistory",
    "ConfigLine",
    "ConfigView",
    "DiffLine",
    "HsrpGroupFact",
    "InterfaceFact",
    "OspfInterfaceFact",
    "POLICY_ALWAYS",
    "POLICY_DISABLED",
    "POLICY_DISCOVERY_ONLY",
    "POLICY_MANUAL",
    "POLICY_SCHEDULED",
    "RECORD_NEW_DEVICE",
    "RECORD_NEW_VERSION",
    "RECORD_UNCHANGED",
    "RecordOutcome",
    "SemanticEvent",
    "TextDiff",
    "TimelineEvent",
    "config_sha256",
    "config_version_id",
    "decide_collection",
    "device_timeline",
    "enterprise_timeline",
    "extract_facts",
    "group_by_day",
    "highest_severity",
    "normalize_policy",
    "semantic_diff",
    "semantic_diff_text",
    "summarize_events",
    "config_view",
    "text_diff",
]
