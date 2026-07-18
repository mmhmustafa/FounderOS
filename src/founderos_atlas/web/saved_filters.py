"""Server-side saved filters, per owner, per surface.

Replaces the write-only ``localStorage`` key: a saved filter is a named
query string persisted under the workspace so it survives browser and
server restarts, appears for the operator who saved it, and can be
listed, applied, renamed, and deleted. Each filter belongs to one
*owner* (the authenticated username, or ``local-operator`` in local
mode) and one *surface* (``evidence``, extensible), so filters are
scoped and never leak across users.

Atomic replace + per-file lock, the same durability contract as every
other Atlas workspace record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

SAVED_FILTERS_FILENAME = "saved-filters.json"
SAVED_FILTERS_SCHEMA_VERSION = "1.0.0"
MAX_PER_OWNER_SURFACE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_query(query: str) -> str:
    """A stable, shareable query string: leading '?' stripped, empty
    values dropped, keys sorted — so equal filters compare equal."""

    from urllib.parse import parse_qsl, urlencode

    pairs = parse_qsl(str(query or "").lstrip("?"), keep_blank_values=False)
    pairs = [(k, v) for k, v in pairs if v != ""]
    pairs.sort()
    return urlencode(pairs)


@dataclass(frozen=True)
class SavedFilter:
    filter_id: str
    owner: str
    surface: str
    name: str
    query: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_id": self.filter_id, "owner": self.owner,
            "surface": self.surface, "name": self.name, "query": self.query,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SavedFilter":
        return cls(
            filter_id=str(value["filter_id"]), owner=str(value["owner"]),
            surface=str(value["surface"]), name=str(value["name"]),
            query=str(value.get("query") or ""),
            created_at=str(value["created_at"]),
            updated_at=str(value.get("updated_at") or value["created_at"]),
        )


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), RLock())


class SavedFilterStore:
    def __init__(self, workspace_root: str | Path) -> None:
        self.path = Path(workspace_root) / SAVED_FILTERS_FILENAME
        self._lock = _lock_for(self.path)

    def _read(self) -> list[SavedFilter]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [
                SavedFilter.from_dict(item)
                for item in raw.get("filters") or ()
            ]
        except (ValueError, TypeError, KeyError):
            return []

    def _write(self, filters: list[SavedFilter]) -> None:
        payload = {
            "schema_version": SAVED_FILTERS_SCHEMA_VERSION,
            "filters": [item.to_dict() for item in filters],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self, *, owner: str, surface: str) -> list[SavedFilter]:
        found = [
            item for item in self._read()
            if item.owner.casefold() == owner.casefold()
            and item.surface == surface
        ]
        found.sort(key=lambda item: item.name.casefold())
        return found

    def get(self, filter_id: str, *, owner: str) -> SavedFilter | None:
        for item in self._read():
            if item.filter_id == filter_id and (
                item.owner.casefold() == owner.casefold()
            ):
                return item
        return None

    def save(
        self, *, owner: str, surface: str, name: str, query: str,
    ) -> SavedFilter:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("a saved filter needs a name")
        with self._lock:
            filters = self._read()
            mine = [
                item for item in filters
                if item.owner.casefold() == owner.casefold()
                and item.surface == surface
            ]
            if len(mine) >= MAX_PER_OWNER_SURFACE:
                raise ValueError(
                    "You have reached the saved-filter limit for this view."
                )
            existing = next(
                (item for item in mine
                 if item.name.casefold() == clean_name.casefold()), None
            )
            stamp = _now()
            record = SavedFilter(
                filter_id=(existing.filter_id if existing
                           else f"filter-{uuid4().hex[:10]}"),
                owner=owner, surface=surface, name=clean_name,
                query=_normalize_query(query),
                created_at=(existing.created_at if existing else stamp),
                updated_at=stamp,
            )
            others = [
                item for item in filters
                if item.filter_id != record.filter_id
            ]
            self._write([*others, record])
            return record

    def rename(
        self, filter_id: str, *, owner: str, name: str,
    ) -> SavedFilter | None:
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("a saved filter needs a name")
        with self._lock:
            filters = self._read()
            updated = None
            result = []
            for item in filters:
                if item.filter_id == filter_id and (
                    item.owner.casefold() == owner.casefold()
                ):
                    from dataclasses import replace

                    updated = replace(item, name=clean, updated_at=_now())
                    result.append(updated)
                else:
                    result.append(item)
            if updated is not None:
                self._write(result)
            return updated

    def delete(self, filter_id: str, *, owner: str) -> bool:
        with self._lock:
            filters = self._read()
            remaining = [
                item for item in filters
                if not (item.filter_id == filter_id
                        and item.owner.casefold() == owner.casefold())
            ]
            if len(remaining) == len(filters):
                return False
            self._write(remaining)
            return True
