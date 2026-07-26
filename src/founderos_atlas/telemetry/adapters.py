"""Outbound telemetry adapter boundary.

Adapters receive already-authorized provider clients or fixture mappings. They
do not own credentials and never perform network I/O in the canonical layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import re
from threading import RLock

from .models import TelemetryFact, fact


class AdapterUnavailableError(RuntimeError):
    pass


class TelemetryAdapter(ABC):
    name: str
    source: str
    evidence_complete: bool = False

    @abstractmethod
    def collect(self, *, scope_id: str) -> tuple[TelemetryFact, ...]:
        """Return normalized facts or raise an explicit availability error."""


class MappingTelemetryAdapter(TelemetryAdapter):
    """Normalize provider-neutral mapping rows behind a named adapter.

    This is the reusable seam for SNMP, syslog, REST, cloud and wireless
    collectors. A production adapter supplies a credential-safe ``reader``;
    Atlas consumers continue to receive only :class:`TelemetryFact`.
    """

    def __init__(
        self,
        name: str,
        reader: Callable[[], Iterable[Mapping]],
        *,
        source: str,
        evidence_complete: bool = False,
    ) -> None:
        self.name = str(name)
        self._reader = reader
        self.source = str(source)
        self.evidence_complete = bool(evidence_complete)

    def collect(self, *, scope_id: str) -> tuple[TelemetryFact, ...]:
        try:
            # Materialize inside the exception boundary: generators can fail
            # during iteration and their provider error text is equally
            # sensitive.
            rows = tuple(self._reader())
        except Exception as error:
            raise AdapterUnavailableError(
                f"{self.name} telemetry provider is unavailable"
            ) from error
        values: list[TelemetryFact] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("telemetry adapter rows must be mappings")
            values.append(fact(
                kind=str(row["kind"]),
                entity_id=str(row["entity_id"]),
                metric=str(row["metric"]),
                value=row["value"],
                unit=str(row.get("unit") or "count"),
                observed_at=str(row["observed_at"]),
                source=self.source,
                adapter=self.name,
                scope_id=scope_id,
                confidence=str(row.get("confidence") or "observed"),
                provider_ref=(
                    str(row["provider_ref"])
                    if row.get("provider_ref") else None
                ),
                metadata=row.get("metadata") or {},
            ))
        return tuple(values)


_ADAPTER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class AdapterStatus:
    name: str
    source: str
    implementation: str
    evidence_complete: bool = False
    state: str = "configured"
    registered_at: str = ""
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_fact_count: int = 0
    error_code: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TelemetryAdapterRegistry:
    """Explicit adapter registration and credential-free runtime status."""

    def __init__(self, adapters: Iterable[TelemetryAdapter] = ()) -> None:
        self._lock = RLock()
        self._adapters: dict[str, TelemetryAdapter] = {}
        self._status: dict[str, AdapterStatus] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(
        self, adapter: TelemetryAdapter, *, replace_existing: bool = False
    ) -> None:
        if not isinstance(adapter, TelemetryAdapter):
            raise TypeError("telemetry adapters must implement TelemetryAdapter")
        name = str(getattr(adapter, "name", "") or "").strip()
        source = str(getattr(adapter, "source", "") or "").strip()
        if not _ADAPTER_NAME.fullmatch(name):
            raise ValueError("telemetry adapter name is invalid")
        if not source or any(ord(char) < 32 for char in source):
            raise ValueError("telemetry adapter source is invalid")
        with self._lock:
            if name in self._adapters and not replace_existing:
                raise ValueError(f"telemetry adapter {name!r} is registered")
            self._adapters[name] = adapter
            self._status[name] = AdapterStatus(
                name=name,
                source=source,
                implementation=type(adapter).__name__,
                evidence_complete=bool(
                    getattr(adapter, "evidence_complete", False)
                ),
                registered_at=_now(),
            )

    def get(self, name: str) -> TelemetryAdapter:
        with self._lock:
            try:
                return self._adapters[str(name)]
            except KeyError as error:
                raise AdapterUnavailableError(
                    "requested telemetry provider is not configured"
                ) from error

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._adapters))

    def statuses(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: status.to_dict()
                for name, status in sorted(self._status.items())
            }

    def mark_attempt(self, name: str) -> None:
        with self._lock:
            current = self._status[name]
            self._status[name] = replace(
                current, state="collecting", last_attempt_at=_now(),
                error_code=None,
            )

    def mark_success(self, name: str, fact_count: int) -> None:
        with self._lock:
            current = self._status[name]
            stamp = _now()
            self._status[name] = replace(
                current, state="available", last_attempt_at=stamp,
                last_success_at=stamp, last_fact_count=max(0, int(fact_count)),
                error_code=None,
            )

    def mark_failure(self, name: str, *, error_code: str) -> None:
        with self._lock:
            current = self._status[name]
            stamp = _now()
            self._status[name] = replace(
                current, state="unavailable", last_attempt_at=stamp,
                last_failure_at=stamp, last_fact_count=0,
                error_code=str(error_code),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
