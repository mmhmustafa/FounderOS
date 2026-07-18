"""Rate limiting for sensitive endpoints, with an adapter boundary.

The built-in limiter is **deliberately in-process and in-memory**:

- fixed one-minute windows per key,
- counters shared by nothing outside this Python process,
- everything resets when the process restarts.

Atlas runs as a single process (discovery jobs are in-process threads),
so this is the correct default — but it means the limits are NOT
enforced across multiple workers or replicas. A multi-worker deployment
must provide a shared implementation (Redis, memcached, a gateway
limiter) behind the same two-method interface below and select it via
``ATLAS_RATE_LIMITER``. Atlas fails loudly at startup rather than
silently running unshared limits under a name it does not recognise.

Layered login limiting (see ``web/security.py``) keys three counters
per attempt: the case-normalized submitted account name (so a
distributed attack against one account is limited regardless of source
addresses), the client source address, and an optional global ceiling.
"""

from __future__ import annotations

import os
import time
from threading import Lock


class RateLimiter:
    """Fixed-window in-process counter. Interface: ``allow`` / ``peek``."""

    scope = "single-process"      # honest capability statement

    def __init__(self) -> None:
        self._hits: dict[tuple[str, int], int] = {}
        self._lock = Lock()

    def allow(
        self, key: str, *, limit: int, window_seconds: int = 60,
        now: float | None = None,
    ) -> bool:
        """Record one hit; True while within ``limit`` per window."""

        stamp = time.monotonic() if now is None else now
        window = int(stamp // window_seconds)
        bucket = (key, window)
        with self._lock:
            # Drop counters from previous windows so memory stays bounded.
            stale = [item for item in self._hits if item[1] < window - 1]
            for item in stale:
                del self._hits[item]
            count = self._hits.get(bucket, 0) + 1
            self._hits[bucket] = count
            return count <= limit

    def peek(
        self, key: str, *, window_seconds: int = 60,
        now: float | None = None,
    ) -> int:
        """Current hit count for ``key`` without recording a hit."""

        stamp = time.monotonic() if now is None else now
        window = int(stamp // window_seconds)
        with self._lock:
            return self._hits.get((key, window), 0)


def resolve_rate_limiter() -> RateLimiter:
    """The configured limiter. ``builtin`` (default) is the in-process
    implementation above; any other name must be a real shared adapter —
    unknown names refuse to start instead of degrading silently."""

    choice = os.environ.get("ATLAS_RATE_LIMITER", "builtin").strip()
    if choice in ("", "builtin"):
        return RateLimiter()
    raise RuntimeError(
        f"ATLAS_RATE_LIMITER={choice!r} is not available in this build. "
        "Provide a shared limiter implementing allow(key, limit=..., "
        "window_seconds=...) and peek(key, ...) and register it here; the "
        "built-in limiter is single-process only and must not impersonate "
        "a shared one."
    )
