"""A small in-process rate limiter for sensitive endpoints.

Fixed-window counting per (key, window). In-process is the right scope
here: Atlas runs as one process (jobs are in-process threads), so a
distributed limiter would be dead weight. The limiter exists to blunt
credential stuffing against /login and hammering of expensive or
sensitive operations — not to be a traffic-shaping product.
"""

from __future__ import annotations

import time
from threading import Lock


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, int], int] = {}
        self._lock = Lock()

    def allow(
        self, key: str, *, limit: int, window_seconds: int = 60,
        now: float | None = None,
    ) -> bool:
        """True if this hit is within ``limit`` per ``window_seconds``."""

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
