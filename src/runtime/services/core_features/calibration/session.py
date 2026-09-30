"""D-321 addendum: the attended calibration session lease.

One robot, at most one calibration session. The session is a heartbeat lease:
the owner (the token that opened it) must renew it within ``ttl_s`` or it
expires. While it is active, every screen shows ``activity: CALIBRATING`` and
the API refuses drive, line-follow and mode writes from any other token
(``CALIBRATION_ACTIVE``). E-stop is never fenced.

Policy only: this object commands nothing (D-2). It never touches the mode
machine or ``cmd_vel``; the routers ask it who may write.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

#: Accepted ``kind`` values are a shape, not a closed list, so a new calibration
#: routine does not need a CORE release. Known values: drive, camera, imu, ir,
#: lidar, odometry.
KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DEFAULT_TTL_S = 30.0
MIN_TTL_S = 5.0
MAX_TTL_S = 300.0
MAX_LABEL_LENGTH = 80


class CalibrationSessionError(Exception):
    """A request the lease refuses. ``code`` is the ERR-102 code."""

    def __init__(self, code: str, message: str, session: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.session = session


@dataclass
class _Session:
    id: str
    kind: str
    label: str
    owner_id: str
    owner_role: str
    owner_label: str
    ttl_s: float
    started_at: str
    started_mono: float
    renewed_mono: float


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


class CalibrationSessionManager:
    def __init__(self, events: Any, *, monotonic: Callable[[], float] = time.monotonic,
                 clock: Callable[[], float] = time.time) -> None:
        self._events = events
        self._monotonic = monotonic
        self._clock = clock
        self._lock = threading.Lock()
        self._session: Optional[_Session] = None

    # --- lease -------------------------------------------------------------

    def start(self, *, kind: str, label: str, ttl_s: float, owner_id: str,
              owner_role: str, owner_label: str = "") -> dict:
        kind = str(kind or "").strip()
        if not KIND_PATTERN.match(kind):
            raise CalibrationSessionError(
                "VALIDATION_ERROR", "kind must match ^[a-z][a-z0-9_]{0,31}$")
        label = str(label or "").strip()[:MAX_LABEL_LENGTH] or kind
        ttl = float(ttl_s)
        if not MIN_TTL_S <= ttl <= MAX_TTL_S:
            raise CalibrationSessionError(
                "VALIDATION_ERROR", f"ttl_s must be within {MIN_TTL_S:g}..{MAX_TTL_S:g}")
        with self._lock:
            self._expire_locked()
            current = self._session
            if current is not None:
                busy = self._public(current)
            else:
                now = self._monotonic()
                current = self._session = _Session(
                    id=secrets.token_hex(8), kind=kind, label=label,
                    owner_id=owner_id, owner_role=owner_role, owner_label=owner_label,
                    ttl_s=ttl, started_at=_iso(self._clock()),
                    started_mono=now, renewed_mono=now)
                busy = None
                opened = self._public(current)
        if busy is not None:
            # One robot, one session. A second one (even from the same token)
            # would hide the first operator's work behind a new label.
            raise CalibrationSessionError(
                "CALIBRATION_ACTIVE", "a calibration session is already active", busy)
        self._events.publish(
            "calibration.session_started", severity="info", source="calibration", data={
            "session_id": opened["id"], "kind": opened["kind"], "label": opened["label"],
            "owner": opened["owner"]["id"], "ttl_s": opened["ttl_s"]})
        return opened

    def heartbeat(self, session_id: str, owner_id: str) -> dict:
        with self._lock:
            self._expire_locked()
            current = self._require_locked(session_id)
            if current is not None and current.owner_id == owner_id:
                current.renewed_mono = self._monotonic()
            snapshot = self._public(current) if current is not None else None
        if snapshot is None:
            raise CalibrationSessionError("NOT_FOUND", "no such active calibration session")
        if snapshot["owner"]["id"] != owner_id:
            raise CalibrationSessionError(
                "FORBIDDEN", "only the session owner can renew it", snapshot)
        return snapshot

    def end(self, session_id: str, *, by_id: str, force: bool = False) -> dict:
        """End the session. ``force`` lets an administrator clear another owner's lease."""
        with self._lock:
            self._expire_locked()
            current = self._require_locked(session_id)
            snapshot = self._public(current) if current is not None else None
            allowed = current is not None and (current.owner_id == by_id or force)
            if allowed:
                self._session = None
        if snapshot is None:
            raise CalibrationSessionError("NOT_FOUND", "no such active calibration session")
        if not allowed:
            raise CalibrationSessionError(
                "FORBIDDEN", "only the session owner or an administrator can end it", snapshot)
        self._events.publish(
            "calibration.session_ended", severity="info", source="calibration", data={
            "session_id": snapshot["id"], "kind": snapshot["kind"],
            "owner": snapshot["owner"]["id"], "by": by_id,
            "duration_s": snapshot["elapsed_s"]})
        return snapshot

    # --- readers -----------------------------------------------------------

    def current(self) -> Optional[dict]:
        with self._lock:
            self._expire_locked()
            snapshot = self._public(self._session) if self._session is not None else None
        return snapshot

    def expire_due(self) -> None:
        """Timer hook: emit the expiry even when nobody is reading state."""
        self.current()

    def activity(self) -> Optional[dict]:
        """The ``activity`` block of the robot state snapshot, or None."""
        session = self.current()
        if session is None:
            return None
        return {
            "kind": "CALIBRATING",
            "session_id": session["id"],
            "calibration_kind": session["kind"],
            "label": session["label"],
            "owner": session["owner"],
            "started_at": session["started_at"],
            "remaining_s": session["remaining_s"],
        }

    def blocking(self, token_id: str) -> Optional[dict]:
        """The active session when ``token_id`` is not its owner, else None."""
        session = self.current()
        if session is None or session["owner"]["id"] == token_id:
            return None
        return session

    # --- internals ---------------------------------------------------------

    def _require_locked(self, session_id: str) -> Optional[_Session]:
        current = self._session
        if current is None or current.id != session_id:
            return None
        return current

    def _expire_locked(self) -> None:
        """Drop a lapsed lease and say so once. Publishing under our lock is safe:
        bus subscribers (audit, sockets) never call back into this object."""
        current = self._session
        if current is None or self._monotonic() - current.renewed_mono < current.ttl_s:
            return
        self._session = None
        self._events.publish(
            "calibration.session_expired", severity="warning", source="calibration",
            data={"session_id": current.id, "kind": current.kind,
                  "owner": current.owner_id, "ttl_s": current.ttl_s})

    def _public(self, session: _Session) -> dict:
        now = self._monotonic()
        return {
            "id": session.id,
            "kind": session.kind,
            "label": session.label,
            "owner": {"id": session.owner_id, "role": session.owner_role,
                      "label": session.owner_label},
            "started_at": session.started_at,
            "ttl_s": session.ttl_s,
            "elapsed_s": round(max(0.0, now - session.started_mono), 1),
            "remaining_s": round(max(0.0, session.ttl_s - (now - session.renewed_mono)), 1),
        }
