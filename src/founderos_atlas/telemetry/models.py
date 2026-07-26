"""Canonical telemetry values consumed by every Atlas engine."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping

_SENSITIVE_METADATA_TERMS = (
    "password", "passwd", "secret", "token", "credential", "privatekey",
    "authorization", "cookie", "apikey",
)
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")


def _safe_metadata(
    value: Mapping[str, Any],
    *,
    depth: int = 0,
) -> dict[str, Any]:
    """Drop secret-shaped fields before telemetry can reach persistence."""

    if depth >= 8:
        return {"_truncated": True}
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:100]:
        key = str(raw_key)[:128]
        normalized = "".join(
            character for character in key.casefold()
            if character.isalnum()
        )
        if any(term in normalized for term in _SENSITIVE_METADATA_TERMS):
            result[key] = "[redacted]"
        else:
            result[key] = _safe_metadata_value(raw_value, depth=depth + 1)
    return result


def _safe_metadata_value(value: Any, *, depth: int) -> Any:
    if depth >= 8:
        return "[truncated]"
    if isinstance(value, Mapping):
        return _safe_metadata(value, depth=depth)
    if isinstance(value, (list, tuple)):
        return [
            _safe_metadata_value(item, depth=depth + 1)
            for item in value[:100]
        ]
    if isinstance(value, str):
        return value[:4096]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported]"

FACT_INTERFACE_UTILIZATION = "interface-utilization"
FACT_INTERFACE_ERRORS = "interface-errors"
FACT_INTERFACE_DISCARDS = "interface-discards"
FACT_LATENCY = "latency"
FACT_LOSS = "loss"
FACT_ROUTE_CHURN = "route-churn"
FACT_OSPF_STATE = "ospf-state"
FACT_BGP_STATE = "bgp-state"
FACT_BGP_PREFIXES = "bgp-prefixes"
FACT_DEVICE_HEALTH = "device-health"
FACT_WIRELESS_CLIENTS = "wireless-clients"
FACT_KINDS = (
    FACT_INTERFACE_UTILIZATION,
    FACT_INTERFACE_ERRORS,
    FACT_INTERFACE_DISCARDS,
    FACT_LATENCY,
    FACT_LOSS,
    FACT_ROUTE_CHURN,
    FACT_OSPF_STATE,
    FACT_BGP_STATE,
    FACT_BGP_PREFIXES,
    FACT_DEVICE_HEALTH,
    FACT_WIRELESS_CLIENTS,
)


def _observed(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("telemetry observed_at must include a timezone")
    return parsed.isoformat(timespec="seconds")


@dataclass(frozen=True)
class TelemetryFact:
    fact_id: str
    kind: str
    entity_id: str
    metric: str
    value: float | int | str | bool
    unit: str
    observed_at: str
    source: str
    adapter: str
    scope_id: str
    confidence: str = "observed"
    collection_id: str | None = None
    provider_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in FACT_KINDS:
            raise ValueError(f"unsupported telemetry fact kind {self.kind!r}")
        for name in (
            "fact_id", "entity_id", "metric", "unit", "source", "adapter",
            "scope_id", "confidence",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be a non-empty string")
        object.__setattr__(self, "observed_at", _observed(self.observed_at))
        if not isinstance(self.value, (float, int, str, bool)):
            raise ValueError("telemetry value must be scalar")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("telemetry metadata must be a mapping")
        object.__setattr__(
            self, "metadata", MappingProxyType(_safe_metadata(self.metadata))
        )
        for name in ("collection_id", "provider_ref"):
            value = getattr(self, name)
            if value is not None:
                cleaned = str(value).strip()
                if cleaned and not _OPAQUE_REF.fullmatch(cleaned):
                    raise ValueError(f"{name} must be an opaque safe reference")
                object.__setattr__(self, name, cleaned or None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind,
            "entity_id": self.entity_id,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "observed_at": self.observed_at,
            "source": self.source,
            "adapter": self.adapter,
            "scope_id": self.scope_id,
            "confidence": self.confidence,
            "collection_id": self.collection_id,
            "provider_ref": self.provider_ref,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TelemetryFact":
        return cls(
            fact_id=str(value["fact_id"]),
            kind=str(value["kind"]),
            entity_id=str(value["entity_id"]),
            metric=str(value["metric"]),
            value=value["value"],
            unit=str(value["unit"]),
            observed_at=str(value["observed_at"]),
            source=str(value["source"]),
            adapter=str(value["adapter"]),
            scope_id=str(value["scope_id"]),
            confidence=str(value.get("confidence") or "observed"),
            collection_id=(
                str(value["collection_id"])
                if value.get("collection_id") else None
            ),
            provider_ref=(
                str(value["provider_ref"]) if value.get("provider_ref")
                else None
            ),
            metadata=value.get("metadata") or {},
        )


def fact(
    *,
    kind: str,
    entity_id: str,
    metric: str,
    value,
    unit: str,
    observed_at: str,
    source: str,
    adapter: str,
    scope_id: str,
    confidence: str = "observed",
    collection_id: str | None = None,
    provider_ref: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> TelemetryFact:
    payload = {
        "kind": kind,
        "entity_id": entity_id,
        "metric": metric,
        "value": value,
        "unit": unit,
        "observed_at": _observed(observed_at),
        "source": source,
        "adapter": adapter,
        "scope_id": scope_id,
        "confidence": confidence,
        "collection_id": collection_id,
        "provider_ref": provider_ref,
        "metadata": _safe_metadata(metadata or {}),
    }
    digest = sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return TelemetryFact(fact_id=f"telemetry:{digest}", **payload)
