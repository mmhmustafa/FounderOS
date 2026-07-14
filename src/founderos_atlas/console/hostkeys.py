"""SSH host-key trust for the Atlas console (PR-044A, CONSOLE).

Atlas had no host-key verification anywhere before this: discovery accepted
whatever key a device presented. An interactive console is a stronger reason
to care — an operator typing into a session believes they are talking to
``core1``.

The policy is trust-on-first-use **with explicit consent**:

- **new** — Atlas has never seen this device's key. Show the fingerprint;
  the operator accepts it deliberately. Atlas does not auto-accept.
- **known** — the key matches what was accepted before. Connect.
- **changed** — the key differs from the accepted one. **Block.** A changed
  host key means the device was rebuilt, replaced, or intercepted, and Atlas
  cannot tell which. It is never silently ignored, and there is no
  "connect anyway" that skips the operator seeing both fingerprints.

The store is a JSON file keyed by ``host:port``, deliberately separate from
the user's own ``~/.ssh/known_hosts``: Atlas accepting a key must not
silently widen the trust of the operator's personal SSH client.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    HOST_KEY_CHANGED,
    HOST_KEY_KNOWN,
    HOST_KEY_NEW,
    HostKeyVerdict,
)


def fingerprint_sha256(key_bytes: bytes) -> str:
    """The OpenSSH-style ``SHA256:…`` fingerprint of a public key blob.

    Same shape the operator sees from ``ssh-keyscan``/OpenSSH, so the two can
    be compared by eye — which is the entire point of showing it.
    """

    digest = hashlib.sha256(key_bytes).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


class HostKeyStore:
    """Atlas's record of the SSH host keys it has been told to trust."""

    def __init__(self, path: Path, *, clock=None) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- persistence ------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt trust store must not silently become an empty one:
            # that would turn every 'changed' verdict into a 'new' one and
            # invite blind re-acceptance. Refuse instead.
            raise HostKeyStoreError(
                f"Atlas's host key store at {self._path} could not be read. "
                "Review or remove the file before opening a console session."
            )
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _key_for(host: str, port: int) -> str:
        return f"{host}:{port}"

    # -- API ---------------------------------------------------------------

    def verify(
        self, host: str, port: int, key_type: str, key_bytes: bytes
    ) -> HostKeyVerdict:
        """Compare a presented key against what Atlas trusts. Read-only."""

        presented = fingerprint_sha256(key_bytes)
        with self._lock:
            entry = self._load().get(self._key_for(host, port))
        if entry is None:
            return HostKeyVerdict(
                status=HOST_KEY_NEW,
                host=host,
                key_type=key_type,
                fingerprint=presented,
            )
        known = str(entry.get("fingerprint") or "")
        if known == presented:
            return HostKeyVerdict(
                status=HOST_KEY_KNOWN,
                host=host,
                key_type=key_type,
                fingerprint=presented,
                known_fingerprint=known,
                known_key_type=entry.get("key_type"),
                first_seen=entry.get("first_seen"),
            )
        return HostKeyVerdict(
            status=HOST_KEY_CHANGED,
            host=host,
            key_type=key_type,
            fingerprint=presented,
            known_fingerprint=known,
            known_key_type=entry.get("key_type"),
            first_seen=entry.get("first_seen"),
        )

    def accept(
        self, host: str, port: int, key_type: str, fingerprint: str
    ) -> None:
        """Record an operator's explicit decision to trust this key.

        Called only from a deliberate acceptance action. Replacing an
        existing entry is allowed — that is an operator overriding a changed
        key on purpose, having been shown both fingerprints.
        """

        now = self._clock().isoformat(timespec="seconds")
        with self._lock:
            data = self._load()
            key = self._key_for(host, port)
            existing = data.get(key) or {}
            data[key] = {
                "host": host,
                "port": port,
                "key_type": key_type,
                "fingerprint": fingerprint,
                "first_seen": existing.get("first_seen") or now,
                "accepted_at": now,
                # An override of a previously trusted key is itself worth
                # remembering; it is the trace of a security decision.
                "replaced_fingerprint": (
                    existing.get("fingerprint")
                    if existing.get("fingerprint")
                    and existing.get("fingerprint") != fingerprint
                    else None
                ),
            }
            self._save(data)

    def forget(self, host: str, port: int) -> bool:
        with self._lock:
            data = self._load()
            removed = data.pop(self._key_for(host, port), None) is not None
            if removed:
                self._save(data)
            return removed

    def known_hosts(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            data = self._load()
        return tuple(
            data[key] for key in sorted(data) if isinstance(data[key], dict)
        )


class HostKeyStoreError(RuntimeError):
    """The trust store exists but cannot be trusted to answer."""
