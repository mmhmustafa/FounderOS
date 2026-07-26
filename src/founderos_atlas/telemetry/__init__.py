"""Vendor-neutral operational telemetry contracts and bounded storage."""

from .adapters import (
    AdapterUnavailableError,
    AdapterStatus,
    MappingTelemetryAdapter,
    TelemetryAdapter,
    TelemetryAdapterRegistry,
)
from .models import (
    FACT_BGP_PREFIXES,
    FACT_BGP_STATE,
    FACT_DEVICE_HEALTH,
    FACT_INTERFACE_DISCARDS,
    FACT_INTERFACE_ERRORS,
    FACT_INTERFACE_UTILIZATION,
    FACT_LATENCY,
    FACT_LOSS,
    FACT_OSPF_STATE,
    FACT_ROUTE_CHURN,
    FACT_WIRELESS_CLIENTS,
    FACT_KINDS,
    TelemetryFact,
    fact,
)
from .store import TelemetryStore
from .orchestration import CollectionResult, TelemetryCollectionService
from .intelligence import OperationalSignal, derive_signals, reconcile_action_center

__all__ = [
    "AdapterUnavailableError",
    "AdapterStatus",
    "CollectionResult",
    "FACT_BGP_PREFIXES",
    "FACT_BGP_STATE",
    "FACT_DEVICE_HEALTH",
    "FACT_INTERFACE_DISCARDS",
    "FACT_INTERFACE_ERRORS",
    "FACT_INTERFACE_UTILIZATION",
    "FACT_KINDS",
    "FACT_LATENCY",
    "FACT_LOSS",
    "FACT_OSPF_STATE",
    "FACT_ROUTE_CHURN",
    "FACT_WIRELESS_CLIENTS",
    "MappingTelemetryAdapter",
    "TelemetryAdapter",
    "TelemetryAdapterRegistry",
    "TelemetryCollectionService",
    "TelemetryFact",
    "TelemetryStore",
    "OperationalSignal",
    "derive_signals",
    "reconcile_action_center",
    "fact",
]
