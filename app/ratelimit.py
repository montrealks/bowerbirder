"""Redis-backed per-IP rate limiting for the anonymous expensive endpoint.

Uses fixed-window counters keyed by client IP and time bucket. Cheap
(one INCR + EXPIRE per check) and shares the existing ``shared-redis``
instance the app already speaks to. Fail-open: if Redis is unavailable
we do not block legitimate traffic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class RateLimitResult:
    allowed: bool
    scope: str = ""          # which window was exceeded ("minute"/"hour"/"day")
    limit: int = 0
    retry_after: int = 0     # seconds until the offending window rolls over


# (scope, window_seconds)
_WINDOWS = (
    ("minute", 60),
    ("hour", 3600),
    ("day", 86400),
)


def check_rate_limit(
    redis_client,
    ip: str,
    *,
    prefix: str,
    per_minute: int,
    per_hour: int,
    per_day: int,
) -> RateLimitResult:
    """Increment fixed-window counters for ``ip`` and report the first
    window (if any) that the request would exceed.

    Counters are only incremented when the request is allowed, so a
    blocked request does not consume additional budget.
    """
    limits = {"minute": per_minute, "hour": per_hour, "day": per_day}
    now = int(time.time())

    try:
        # First pass: read current counts without mutating, so a rejected
        # request in one window doesn't burn budget in the others.
        pipe = redis_client.pipeline()
        keys = []
        for scope, window in _WINDOWS:
            bucket = now // window
            key = f"{prefix}:rl:{scope}:{ip}:{bucket}"
            keys.append((scope, window, key))
            pipe.get(key)
        current = pipe.execute()

        for (scope, window, _key), raw in zip(keys, current):
            count = int(raw) if raw is not None else 0
            limit = limits[scope]
            if limit > 0 and count >= limit:
                retry_after = window - (now % window)
                return RateLimitResult(
                    allowed=False, scope=scope, limit=limit, retry_after=retry_after
                )

        # Allowed: now atomically increment every window.
        pipe = redis_client.pipeline()
        for scope, window, key in keys:
            pipe.incr(key)
            pipe.expire(key, window)
        pipe.execute()
        return RateLimitResult(allowed=True)
    except Exception:
        # Redis hiccup must never take down legitimate job submission.
        return RateLimitResult(allowed=True)


def get_trusted_client_ip(request) -> str:
    """Return the real client IP.

    The Caddy edge (with Cloudflare ``trusted_proxies``) sets ``X-Real-IP``
    from the Cloudflare-verified ``Cf-Connecting-Ip`` and strips any
    client-forged value. Raw ``X-Forwarded-For`` is client-spoofable and is
    deliberately NOT consulted here.
    """
    real_ip: Optional[str] = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    cf_ip: Optional[str] = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    return request.client.host if request.client else "unknown"
