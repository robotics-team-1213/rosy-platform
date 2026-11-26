"""A route-owned, short-lived speed ceiling used at every Nav2 output selection."""
from __future__ import annotations

import math
import time
import threading


MAX_GRANT_S = 2.0


class RoadSpeedAuthority:
    def __init__(self):
        self._lock = threading.Lock()
        self._grant = (0.0, 0.0, 0.0)  # issue time, local monotonic expiry, linear ceiling

    def update(self, issued_at, expires_at, limit_mps, lease_ttl_s):
        from .manager import NavigationError
        with self._lock:
            now = time.time()
            if (not all(math.isfinite(v) for v in (issued_at, expires_at, limit_mps))
                    or limit_mps < 0 or not issued_at <= now < expires_at
                    or expires_at - issued_at > MAX_GRANT_S or issued_at <= self._grant[0]):
                raise NavigationError("VALIDATION_ERROR", "expired, unordered or invalid road speed grant")
            self._grant = (issued_at, time.monotonic() + min(lease_ttl_s, expires_at - now), limit_mps)

    def close(self):
        with self._lock:
            self._grant = (math.inf, 0.0, 0.0)

    def apply(self, linear, angular, now):
        _, deadline, cap = self._grant
        if now >= deadline or cap <= 0:
            return 0.0, 0.0
        if abs(linear) <= cap:
            return linear, angular
        scale = cap / abs(linear)
        return linear * scale, angular * scale

    def submit(self, linear, angular, send, hold):
        if not self._lock.acquire(blocking=False):
            return hold()
        try:
            if self.apply(linear, angular, time.monotonic()) != (linear, angular):
                return hold()
            return send()
        finally:
            self._lock.release()
