"""Console connection audit (PR-044A, CONSOLE).

Records **that** a session happened — never what was said in it. The spec is
explicit: no terminal commands or output are recorded by default. That is a
deliberate privacy position, not an oversight, and it is also why this log
is safe to keep: it can never contain a configuration secret an engineer
typed.

Recorded per connection: operator, canonical device, management endpoint,
credential *reference* id, connected time, disconnected time, result.

Optional audited command recording is future work. It would be an explicit,
off-by-default setting, and would need its own secret-masking pass before a
single byte was written.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ConsoleAuditLog:
    """Append-only JSON-lines record of console connections."""

    def __init__(self, path: Path, *, clock=None) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def record(
        self,
        event: str,
        *,
        session_id: str,
        operator: str,
        device_id: str,
        hostname: str,
        management_ip: str,
        port: int,
        credential_ref: str | None,
        result: str | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        """Append one connection event.

        ``detail`` carries an operator-facing reason (e.g. "authentication
        failed"), never an exception trace and never device output.
        """

        entry = {
            "at": self._now(),
            "event": event,
            "session_id": session_id,
            "operator": operator,
            "device_id": device_id,
            "hostname": hostname,
            "management_ip": management_ip,
            "port": port,
            # A reference names a secret; it is not one.
            "credential_ref": credential_ref,
            "result": result,
            "detail": detail,
        }
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def entries(self, *, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        """Recorded events, newest last. Missing log is empty, not an error."""

        if not self._path.exists():
            return ()
        rows: list[dict[str, Any]] = []
        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue     # a torn line must not hide the rest
                if isinstance(parsed, dict):
                    rows.append(parsed)
        if limit:
            return tuple(rows[-limit:])
        return tuple(rows)
