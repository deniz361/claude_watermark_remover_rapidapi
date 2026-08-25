"""Gate the service behind the RapidAPI proxy and throttle per subscriber.

Rapid adds X-RapidAPI-Proxy-Secret to every request it forwards. It is the only
thing separating "a paying subscriber" from "anyone who found the origin URL",
so a request without it is refused outright.
"""

from __future__ import annotations

from collections import deque
import secrets
import threading
import time

from fastapi import Request

from config import Settings
from errors import ApiError

PROXY_SECRET_HEADER = "X-RapidAPI-Proxy-Secret"
USER_HEADER = "X-RapidAPI-User"
SUBSCRIPTION_HEADER = "X-RapidAPI-Subscription"


def require_proxy_secret(request: Request, settings: Settings) -> None:
    if not settings.proxy_secret_configured:
        # Failing closed matters more than uptime here: without the secret the
        # service cannot tell Rapid traffic from anyone else's.
        raise ApiError(
            503,
            "proxy_secret_not_configured",
            "This deployment is not configured to accept RapidAPI traffic.",
        )
    presented = request.headers.get(PROXY_SECRET_HEADER) or ""
    if not secrets.compare_digest(presented, settings.proxy_secret):
        raise ApiError(
            403,
            "proxy_secret_invalid",
            "This endpoint only accepts requests forwarded by RapidAPI.",
        )


def consumer_identity(request: Request) -> str:
    """Identify the subscriber for throttling.

    Rapid enforces plan quotas at its own proxy, but that does not stop one
    subscriber bursting their whole monthly allowance in a few seconds.
    """
    user = (request.headers.get(USER_HEADER) or "").strip()
    if user:
        return f"user:{user}"
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    return "anonymous"


def subscription_tier(request: Request) -> str | None:
    tier = (request.headers.get(SUBSCRIPTION_HEADER) or "").strip()
    return tier or None


class RateLimiter:
    """Fixed-memory sliding window, keyed by subscriber.

    Endpoints are synchronous so Starlette runs them in a worker thread; the
    lock is what keeps concurrent requests from corrupting a window. State is
    per process, so several workers each allow the configured rate.
    """

    #: How often to sweep windows belonging to subscribers who stopped calling.
    PRUNE_INTERVAL_SECONDS = 300.0

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._pruned_at = time.monotonic()

    def retry_after(self, identity: str, limit: int, window_seconds: int) -> int:
        """Return seconds to wait, or 0 when the request is allowed through."""
        if limit <= 0 or window_seconds <= 0:
            return 0
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits.get(identity)
            if hits is None:
                hits = self._hits[identity] = deque()
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(window_seconds - (now - hits[0])) + 1)
            hits.append(now)
            self._prune(now, window_seconds)
        return 0

    def _prune(self, now: float, window_seconds: float) -> None:
        """Drop windows that have fully expired. Caller must hold the lock."""
        if now - self._pruned_at < self.PRUNE_INTERVAL_SECONDS:
            return
        self._pruned_at = now
        cutoff = now - window_seconds
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._pruned_at = time.monotonic()
