"""Immutable in-memory structured artifact content storage."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from threading import RLock
from typing import Any

from .errors import DuplicateRecordError, RecordNotFoundError


class InMemoryContentStore:
    """Store canonical JSON content by immutable memory URI and digest."""

    def __init__(self, lock: RLock | None = None) -> None:
        self.lock = lock or RLock()
        self._content: dict[str, dict[str, Any]] = {}

    @staticmethod
    def canonical_bytes(content: dict[str, Any]) -> bytes:
        return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def put(self, uri: str, content: dict[str, Any]) -> tuple[str, str]:
        with self.lock:
            if uri in self._content:
                raise DuplicateRecordError(f"Artifact content already exists: {uri}")
            payload = self.canonical_bytes(content)
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            self._content[uri] = deepcopy(content)
            return uri, digest

    def get(self, uri: str) -> dict[str, Any]:
        with self.lock:
            try:
                return deepcopy(self._content[uri])
            except KeyError as error:
                raise RecordNotFoundError(f"Artifact content not found: {uri}") from error

    def _snapshot(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._content)

    def _restore(self, snapshot: dict[str, dict[str, Any]]) -> None:
        self._content = deepcopy(snapshot)
