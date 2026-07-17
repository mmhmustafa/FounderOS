"""Enterprise Memory — Atlas's long-term persistence layer (PR-045, MEMORY).

Discovery tells Atlas what the network looks like now. Enterprise Memory is
what lets it also answer: what changed, when, what a device looked like
before, show me discovery #17. This package is the *foundation* only — it
persists and retrieves; nothing interprets or diffs here (that is deliberately
left to future modules).

The layer, top to bottom:

- ``models``    immutable, content-addressed records (sessions, raw evidence,
                configuration snapshots, observations, device memory)
- ``store``     the durable content-addressed blob store: gzip-compressed,
                deduplicated, append-only
- ``retrieval`` the stable read API future consumers call (masked view vs
                raw download)
- ``sink``      captures raw evidence during a discovery that already ran —
                no second session, no rediscovery

Design commitments: collection is separated from interpretation (raw evidence
is preserved even if today's parser cannot fully use it, so a future parser
can reprocess history without reconnecting); everything is immutable and
content-addressed; and the model is source-agnostic, so Syslog / SNMP /
NetFlow / telemetry become new evidence sources without a redesign.
"""

from __future__ import annotations

from .fingerprint import ConfigurationFingerprint, fingerprint
from .models import (
    ATLAS_VERSION,
    COLLECTION_EMPTY,
    COLLECTION_ERROR,
    COLLECTION_OK,
    COLLECTION_UNAVAILABLE,
    MODE_CIDR,
    MODE_IMPORTED,
    MODE_SEED,
    PARSER_VERSION,
    SESSION_COMPLETED,
    SESSION_FAILED,
    SESSION_INTERRUPTED,
    SESSION_RUNNING,
    SOURCE_CLI,
    TRANSPORT_SSH,
    BlobObservation,
    ConfigurationSnapshot,
    DeviceMemory,
    DiscoverySession,
    RawEvidenceRecord,
    content_sha256,
)
from .retrieval import EnterpriseMemory, EvidenceView
from .sink import EvidenceSink
from .store import EnterpriseMemoryStore


__all__ = [
    "COLLECTION_EMPTY",
    "COLLECTION_ERROR",
    "COLLECTION_OK",
    "COLLECTION_UNAVAILABLE",
    "MODE_CIDR",
    "MODE_IMPORTED",
    "MODE_SEED",
    "PARSER_VERSION",
    "SESSION_COMPLETED",
    "SESSION_FAILED",
    "SESSION_INTERRUPTED",
    "SESSION_RUNNING",
    "SOURCE_CLI",
    "ATLAS_VERSION",
    "BlobObservation",
    "ConfigurationFingerprint",
    "ConfigurationSnapshot",
    "DeviceMemory",
    "DiscoverySession",
    "EnterpriseMemory",
    "EnterpriseMemoryStore",
    "EvidenceSink",
    "EvidenceView",
    "RawEvidenceRecord",
    "TRANSPORT_SSH",
    "content_sha256",
    "fingerprint",
]
