"""Token-bucket rate limiter, thread-safe, in-memory.

Why token bucket
----------------
We use the classic token-bucket algorithm: each IP gets a bucket of
``burst`` tokens that refills at ``rate`` tokens/second. A request
consumes one token; if the bucket is empty the request is denied with a
``retry_after`` hint. Token bucket is preferable to a fixed window because
it absorbs short bursts (e.g. a user firing several clicks in a row)
while still bounding the long-term rate.

Why not asyncio
---------------
The bucket map is guarded by a plain ``threading.Lock`` rather than
``asyncio.Lock``. This keeps the implementation usable from sync
call-sites (CLI smoke tests, batch jobs) and avoids the lock-vs-event-loop
footgun when middleware is mounted on a non-async ASGI server.

Limitations
-----------
**Single-process.** The bucket map lives in process memory; each
``uvicorn --workers N`` worker has its own state. For multi-worker
deployments, swap this implementation for one backed by Redis (or any
shared store) — see SECURITY.md "Operational notes".
"""

from __future__ import annotations

import threading
import time
from typing import Any


class TokenBucket:
    """Thread-safe token bucket. Refills at ``rate`` tokens/sec, capacity ``burst``."""

    __slots__ = ("_lock", "burst", "last_refill", "rate", "tokens")

    def __init__(self, rate: float, burst: int) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate!r}")
        if burst < 1:
            raise ValueError(f"burst must be >= 1, got {burst!r}")
        self.rate = float(rate)
        self.burst = int(burst)
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self, tokens: int = 1) -> bool:
        """Consume ``tokens`` tokens if available; return True on success.

        Refills the bucket based on elapsed time before checking capacity.
        """
        if tokens < 1:
            raise ValueError(f"tokens must be >= 1, got {tokens!r}")
        with self._lock:
            self._refill_locked()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def time_to_refill(self, tokens: int = 1) -> float:
        """Seconds until at least ``tokens`` tokens would be available.

        If the bucket already has enough, returns 0.0.
        """
        if tokens < 1:
            raise ValueError(f"tokens must be >= 1, got {tokens!r}")
        with self._lock:
            self._refill_locked()
            if self.tokens >= tokens:
                return 0.0
            deficit = tokens - self.tokens
            # rate tokens/sec → seconds needed
            return deficit / self.rate

    def _refill_locked(self) -> None:
        """Refill tokens based on elapsed time. Call with ``_lock`` held."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_refill = now


class RateLimiter:
    """Per-key (e.g. per-IP) token buckets, with TTL eviction.

    The map of buckets can grow without bound over the process lifetime;
    the TTL eviction sweeps buckets that have not been used within
    ``ttl_seconds``, keeping memory bounded for long-running servers.
    """

    def __init__(
        self,
        rate: float,
        burst: int,
        ttl_seconds: float = 300.0,
        *,
        _time_source: Any = None,
    ) -> None:
        self.rate = float(rate)
        self.burst = int(burst)
        self.ttl_seconds = float(ttl_seconds)
        # last-access map keyed by the same key as the buckets
        self._buckets: dict[str, tuple[TokenBucket, float]] = {}
        self._lock = threading.Lock()
        # injectable clock makes testing easy without monkeypatching
        # time.monotonic globally; defaults to time.monotonic.
        self._time = _time_source if _time_source is not None else time.monotonic

    def check(self, key: str) -> tuple[bool, float]:
        """Decide whether ``key`` may proceed.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds``
        is 0.0 when ``allowed`` is True, and the time until enough tokens
        refill otherwise. Evicts stale buckets opportunistically.
        """
        now = self._time()
        with self._lock:
            entry = self._buckets.get(key)
            if entry is None:
                bucket = TokenBucket(self.rate, self.burst)
                self._buckets[key] = (bucket, now)
                # Re-fetch so we own the freshly inserted bucket for the
                # rest of this call.
                entry = self._buckets[key]
            bucket = entry[0]
            allowed = bucket.try_acquire(1)
            retry_after = 0.0 if allowed else bucket.time_to_refill(1)
            # update last-access; opportunistically evict stale entries
            self._buckets[key] = (bucket, now)
            # Cheap eviction: only when the map is reasonably small.
            # For very large maps we would switch to a periodic sweep,
            # but for the volumes a single firm-bot process sees this
            # approach avoids holding the lock for long.
            if len(self._buckets) > 1024:
                self._evict_stale_locked(now)
            return allowed, retry_after

    def reset(self) -> None:
        """Drop all buckets. Primarily for tests."""
        with self._lock:
            self._buckets.clear()

    def size(self) -> int:
        """Current number of tracked keys (for tests / metrics)."""
        with self._lock:
            return len(self._buckets)

    def _evict_stale_locked(self, now: float) -> None:
        """Drop buckets last accessed more than ``ttl_seconds`` ago.

        Call with ``_lock`` held. Worst-case O(N) per check; we only
        trigger this when the map exceeds 1024 entries to avoid
        pathological behaviour under load.
        """
        ttl = self.ttl_seconds
        # Capture keys to avoid mutating the dict during iteration.
        stale = [k for k, (_, last) in self._buckets.items() if now - last > ttl]
        for k in stale:
            self._buckets.pop(k, None)
