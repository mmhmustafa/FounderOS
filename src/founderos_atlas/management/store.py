"""Persistence for verified and operator-defined management services
(PR-044B, PORTAL).

Two kinds of record live here, kept clearly apart:

- **auto-verified** — what a probe established. Keyed by
  ``device_id / protocol / port``; re-verification updates ``last_verified``
  and can raise a certificate-change flag against the stored fingerprint.
- **operator-defined** — a URL an engineer stated when automatic verification
  could not. It carries who, when, and why, and is never silently promoted to
  "verified by Atlas" — the UI shows its origin.

No credential is ever stored. A management service is an address and what
Atlas can prove about it.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    PROTOCOL_HTTP,
    PROTOCOL_HTTPS,
    SOURCE_OPERATOR,
    VERIFICATION_OPERATOR,
    ManagementService,
)


class ManagementServiceStore:
    """The management services Atlas knows for one scope."""

    def __init__(self, path: Path, *, clock=None) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- persistence ------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"services": [], "overrides": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"services": [], "overrides": []}
        data.setdefault("services", [])
        data.setdefault("overrides", [])
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    # -- auto-verified services -------------------------------------------

    def services_for(self, device_id: str) -> tuple[ManagementService, ...]:
        with self._lock:
            data = self._load()
        found = [
            ManagementService.from_dict(item)
            for item in data["services"]
            if item.get("device_id") == device_id
        ]
        found.extend(self._overrides_for(device_id, data))
        return tuple(found)

    def all_services(self) -> tuple[ManagementService, ...]:
        with self._lock:
            data = self._load()
        result = [ManagementService.from_dict(item) for item in data["services"]]
        for item in data["overrides"]:
            result.append(self._override_to_service(item))
        return tuple(result)

    def known_index(
        self, device_id: str
    ) -> dict[tuple[str, int], ManagementService]:
        """``(protocol, port) -> service`` for carry-forward and change
        detection during re-verification."""

        return {
            (service.protocol, service.port): service
            for service in self.services_for(device_id)
            if not service.operator_defined
        }

    def record_services(
        self, device_id: str, services: tuple[ManagementService, ...]
    ) -> None:
        """Replace this device's auto-verified services with a fresh set.

        Operator overrides are never touched here — they live in their own
        list and outlive any re-probe.
        """

        with self._lock:
            data = self._load()
            data["services"] = [
                item
                for item in data["services"]
                if item.get("device_id") != device_id
            ]
            data["services"].extend(service.to_dict() for service in services)
            self._save(data)

    # -- operator-defined endpoints ---------------------------------------

    def define_endpoint(
        self,
        device_id: str,
        *,
        url: str,
        protocol: str,
        address: str,
        port: int,
        user: str,
        reason: str | None = None,
    ) -> ManagementService:
        """Record an operator's stated management URL.

        This is a claim by a person, not a verification by Atlas. It is stored
        as ``operator-defined`` and presented as such — never dressed up as
        something Atlas proved.
        """

        now = self._clock().isoformat(timespec="seconds")
        entry = {
            "device_id": device_id,
            "url": url,
            "protocol": protocol,
            "address": address,
            "port": int(port),
            "defined_by": user,
            "defined_at": now,
            "reason": reason,
        }
        with self._lock:
            data = self._load()
            data["overrides"] = [
                item
                for item in data["overrides"]
                if not (
                    item.get("device_id") == device_id
                    and item.get("url") == url
                )
            ]
            data["overrides"].append(entry)
            self._save(data)
        return self._override_to_service(entry)

    def clear_override(self, device_id: str, url: str) -> bool:
        with self._lock:
            data = self._load()
            before = len(data["overrides"])
            data["overrides"] = [
                item
                for item in data["overrides"]
                if not (
                    item.get("device_id") == device_id and item.get("url") == url
                )
            ]
            if len(data["overrides"]) != before:
                self._save(data)
                return True
        return False

    def _overrides_for(
        self, device_id: str, data: dict[str, Any]
    ) -> list[ManagementService]:
        return [
            self._override_to_service(item)
            for item in data["overrides"]
            if item.get("device_id") == device_id
        ]

    def _override_to_service(self, entry: dict[str, Any]) -> ManagementService:
        protocol = str(entry.get("protocol") or PROTOCOL_HTTPS)
        return ManagementService(
            device_id=str(entry["device_id"]),
            address=str(entry.get("address") or ""),
            protocol=protocol if protocol in (PROTOCOL_HTTPS, PROTOCOL_HTTP) else PROTOCOL_HTTPS,
            port=int(entry.get("port") or (443 if protocol == PROTOCOL_HTTPS else 80)),
            verification=VERIFICATION_OPERATOR,
            evidence="operator-defined",
            source=SOURCE_OPERATOR,
            first_observed=entry.get("defined_at"),
            last_verified=entry.get("defined_at"),
            defined_by=entry.get("defined_by"),
            defined_at=entry.get("defined_at"),
            reason=entry.get("reason"),
            detail="Operator-defined endpoint — stated by a person, not verified by Atlas.",
        )
