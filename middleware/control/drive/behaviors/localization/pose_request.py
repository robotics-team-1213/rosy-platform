"""core_features.localization.pose_request — D-546 5: CORE asks Fleet for its pose.

When D-468 lane_return cannot go on for want of a pose (`pose_stale`, `fleet_required`)
CORE opens one request that Fleet reads at `GET /localization/request`. The request only
asks: Fleet answers with the existing `POST /localization/decision` and the robot's own
3 s scan check still decides (D-395). One request per reason; the same reason keeps its
id and `created_at` while it stays open and only refreshes the evidence. A request older
than `ttl_s` is gone, and the next `open` makes a new one, so a lost answer is asked again.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping, Optional

#: Lifetime of one request; Fleet ignores an older one. Open question 2 of D-546.
REQUEST_TTL_S = 30.0
REASONS = ("pose_stale", "fleet_required")


class PoseRequests:
    def __init__(self, events, robot_id: Callable[[], str], *,
                 clock: Callable[[], float] = time.time, ttl_s: float = REQUEST_TTL_S) -> None:
        self._events = events
        self._robot_id = robot_id
        self._clock = clock
        self._ttl_s = float(ttl_s)
        self._lock = threading.Lock()
        self._request: Optional[dict[str, Any]] = None
        self._count = 0

    def open(self, reason: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
        if reason not in REASONS:
            raise ValueError(f"unknown pose request reason {reason!r}")
        now = self._clock()
        with self._lock:
            current = self._live(now)
            if current is not None and current["reason"] == reason:
                current["evidence"] = dict(evidence)
                return dict(current)
            self._count += 1
            self._request = {"request_id": f"pose-{int(now * 1000)}-{self._count}",
                             "robot_id": self._robot_id(), "reason": reason,
                             "created_at": now, "ttl_s": self._ttl_s, "evidence": dict(evidence)}
            opened = dict(self._request)
        self._events.publish("localization.request", source="localization", data={
            "request_id": opened["request_id"], "reason": reason})
        return opened

    def clear(self, why: str) -> bool:
        """Drop the open request; True when there was one."""
        with self._lock:
            request, self._request = self._request, None
        if request is None:
            return False
        self._events.publish("localization.request_cleared", source="localization", data={
            "request_id": request["request_id"], "why": why})
        return True

    def current(self) -> Optional[dict[str, Any]]:
        """The open request with its `age_s`, or None once it is older than its `ttl_s`."""
        now = self._clock()
        with self._lock:
            request = self._live(now)
            return None if request is None else {**request, "age_s": max(0.0, now - request["created_at"])}

    def _live(self, now: float) -> Optional[dict[str, Any]]:
        """The caller holds the lock."""
        request = self._request
        if request is not None and now - request["created_at"] > request["ttl_s"]:
            self._request = request = None
        return request
