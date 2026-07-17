"""Enterprise Memory retrieval API (PR-045, MEMORY, Part 7).

A stable read facade over the store. This is the interface future consumers
(Mission, Advisor, Prediction, Investigation, Compliance, Incident, AI) will
call — so it is deliberately small, explicit, and free of UI concerns.

Two ways to read stored text:

- ``download_*`` returns the exact raw bytes, for the local operator. A
  ``show running-config`` contains secrets; download is the one path where the
  raw text is the point, exactly as configuration export already works.
- ``view_*`` returns the text **masked** through the existing
  ``config_intelligence.mask_line``, so a credential never reaches a rendered
  page. This is the default for anything shown in the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from founderos_atlas.config_intelligence import mask_line

from .models import (
    ConfigurationSnapshot,
    DeviceMemory,
    DiscoverySession,
    RawEvidenceRecord,
)
from .store import EnterpriseMemoryStore


@dataclass(frozen=True)
class EvidenceView:
    """One piece of raw evidence, prepared for display (masked)."""

    record: RawEvidenceRecord
    text: str | None
    masked_line_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "text": self.text,
            "masked_line_count": self.masked_line_count,
        }


class EnterpriseMemory:
    """The retrieval service. Read-only over one scope's memory store."""

    def __init__(self, store: EnterpriseMemoryStore) -> None:
        self._store = store

    # -- discovery sessions ------------------------------------------------

    def list_discovery_sessions(self) -> tuple[DiscoverySession, ...]:
        return self._store.list_sessions()

    def get_discovery_session(self, session_id: str) -> DiscoverySession | None:
        return self._store.get_session(session_id)

    def session_devices(self, session_id: str) -> tuple[dict[str, Any], ...]:
        """The devices touched by one session, with their evidence + config
        counts — enough to render a session detail page."""

        records = self._store.evidence_records(discovery_session=session_id)
        snapshots = self._store.configuration_snapshots()
        by_device: dict[str, dict[str, Any]] = {}
        for record in records:
            entry = by_device.setdefault(
                record.device_id,
                {"device_id": record.device_id, "hostname": record.hostname,
                 "evidence_count": 0, "configuration": None},
            )
            entry["evidence_count"] += 1
            entry["hostname"] = entry["hostname"] or record.hostname
        for snap in snapshots:
            if snap.discovery_session != session_id:
                continue
            entry = by_device.setdefault(
                snap.device_id,
                {"device_id": snap.device_id, "hostname": snap.hostname,
                 "evidence_count": 0, "configuration": None},
            )
            entry["configuration"] = snap.to_dict()
            entry["hostname"] = entry["hostname"] or snap.hostname
        return tuple(sorted(by_device.values(), key=lambda d: d["hostname"].casefold()))

    # -- device history ----------------------------------------------------

    def get_device_memory(self, device_id: str) -> DeviceMemory | None:
        return self._store.device_memory(device_id)

    def device_ids(self) -> tuple[str, ...]:
        return self._store.device_ids()

    def get_configuration_history(
        self, device_id: str
    ) -> tuple[ConfigurationSnapshot, ...]:
        return self._store.configuration_snapshots(device_id=device_id)

    def get_raw_evidence(self, device_id: str) -> tuple[RawEvidenceRecord, ...]:
        return self._store.evidence_records(device_id=device_id)

    # -- timelines (Part 8): ordered histories future modules read ---------

    def evidence_timeline(
        self, device_id: str, *, newest_first: bool = True
    ) -> tuple[RawEvidenceRecord, ...]:
        """This device's raw evidence, ordered by collection time."""

        records = list(self._store.evidence_records(device_id=device_id))
        records.sort(key=lambda r: r.collected_at, reverse=newest_first)
        return tuple(records)

    def configuration_timeline(
        self, device_id: str, *, newest_first: bool = True
    ) -> tuple[ConfigurationSnapshot, ...]:
        """This device's configuration snapshots, ordered by capture time."""

        snaps = list(self._store.configuration_snapshots(device_id=device_id))
        snaps.sort(key=lambda s: s.captured_at, reverse=newest_first)
        return tuple(snaps)

    # -- raw text (download = raw; view = masked) --------------------------

    def download_evidence(self, content_sha256: str) -> str | None:
        return self._store.evidence_text(content_sha256)

    def download_configuration(self, config_sha256: str) -> str | None:
        return self._store.configuration_text(config_sha256)

    def view_evidence(self, record: RawEvidenceRecord) -> EvidenceView:
        raw = (
            self._store.evidence_text(record.content_sha256)
            if record.content_sha256
            else None
        )
        if raw is None:
            return EvidenceView(record=record, text=None, masked_line_count=0)
        masked, count = _mask_text(raw)
        return EvidenceView(record=record, text=masked, masked_line_count=count)

    def view_configuration(self, config_sha256: str) -> tuple[str | None, int]:
        raw = self._store.configuration_text(config_sha256)
        if raw is None:
            return None, 0
        return _mask_text(raw)

    # -- statistics --------------------------------------------------------

    def statistics(self) -> dict[str, Any]:
        return self._store.statistics()


def _mask_text(text: str) -> tuple[str, int]:
    """Mask every line that contains a secret; return (text, masked_count)."""

    lines = text.splitlines()
    masked = []
    count = 0
    for line in lines:
        rendered = mask_line(line)
        if rendered != line:
            count += 1
        masked.append(rendered)
    return "\n".join(masked), count
