"""D-411 A: CORE's Pilot recording guard. ROS-free; ros_bridge wires the transport.

CORE only asks the camera unit's recorder to start or stop. It stops a recording when the
owner's /ws/state link is gone for LINK_GRACE_S, or when another token's teleop is accepted.
CORE has no Pilot seat, so "link" is the owner token's open /ws/state sockets and "seat
change" is an accepted teleop from another token. Both are judged on each recorder status
(1 Hz) and on each accepted teleop; no timer of its own.

request_active(on, wait) -> (ok, message): the bridge's SetBool call. message is the
recorder's {"code", "status"} JSON. Stops the guard decides itself use wait=False: they
run on executor callbacks, where waiting for a service reply would deadlock.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional

from core_common.protocol.recording import RecorderStatus

STATUS_STALE_S = 3.0
LINK_GRACE_S = 5.0
_REFUSAL_STATUS = {"RECORDING_BUSY": 409, "RECORDING_QUOTA_FULL": 507, "RECORDING_DISK_FULL": 507,
                   "RECORDING_NOT_ACTIVE": 409, "RECORDER_UNAVAILABLE": 503}
_ACTIVE = ("recording", "stopping")


class RecordingRefused(Exception):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


def _refused(code: str, message: str) -> RecordingRefused:
    return RecordingRefused(code, _REFUSAL_STATUS.get(code, 503), message)


class PilotRecordingGuard:
    def __init__(self, *, events=None, clock: Callable[[], float] = time.monotonic) -> None:
        self._events = events
        self._clock = clock
        self._lock = threading.Lock()
        self._status: Optional[dict] = None
        self._status_at = float("-inf")
        self._owner: Optional[str] = None
        self._links: dict[str, int] = {}
        self._lost_at: Optional[float] = None
        #: (on, wait) -> (ok, message). None until the ROS bridge is wired.
        self.request_active: Optional[Callable[[bool, bool], tuple[bool, str]]] = None
        #: recording id -> None. Tells the recorder a recording left in full.
        self.publish_fetched: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------- reading
    def _fresh_status(self) -> Optional[dict]:
        if self._status is None or self._clock() - self._status_at > STATUS_STALE_S:
            return None
        return self._status

    def status(self) -> Optional[dict]:
        """The last recorder status; None when it is stale or never arrived."""
        with self._lock:
            status = self._fresh_status()
            return None if status is None else dict(status)

    def active(self) -> bool:
        """A session runs or is still being finished (manifest hashing)."""
        status = self.status()
        return status is not None and status["state"] in _ACTIVE

    def owner(self) -> Optional[str]:
        with self._lock:
            return self._owner

    # -------------------------------------------------------------- inputs
    def on_status(self, payload: dict) -> None:
        """Validates a recorder status (ValueError otherwise) and judges the owner's link."""
        status = RecorderStatus.model_validate(payload).model_dump(by_alias=True)
        ended = None
        with self._lock:
            previous = self._status
            self._status, self._status_at = status, self._clock()
            if status["state"] not in _ACTIVE and self._owner is not None:
                ended = (previous["id"] if previous else None,
                         status["last_stop_reason"] or "recorder_exit")
                self._owner, self._lost_at = None, None
        if ended is not None:
            self._stopped(ended[0], None, ended[1])
            return
        self._check_link()

    def link_opened(self, token_id: str) -> None:
        with self._lock:
            self._links[token_id] = self._links.get(token_id, 0) + 1
            if token_id == self._owner:
                self._lost_at = None

    def link_closed(self, token_id: str) -> None:
        with self._lock:
            left = self._links.get(token_id, 0) - 1
            if left > 0:
                self._links[token_id] = left
            else:
                self._links.pop(token_id, None)

    def on_teleop(self, token_id: str) -> None:
        """An accepted teleop. Another token driving is a seat change."""
        with self._lock:
            changed = self._recording_owner() not in (None, token_id)
        if changed:
            self._stop_async("seat_changed")

    # ------------------------------------------------------------- actions
    def start(self, token_id: str) -> dict:
        request = self.request_active
        with self._lock:
            status = self._fresh_status()
        if request is None or status is None:
            raise _refused("RECORDER_UNAVAILABLE", "the camera unit's recorder is not reporting")
        if status["state"] in _ACTIVE:
            raise _refused("RECORDING_BUSY", "a recording is running or still being finished")
        ok, message = request(True, True)
        body = self._reply(message)
        if not ok:
            code = body.get("code") or "RECORDER_UNAVAILABLE"
            raise _refused(code, f"the recorder refused to start: {code}")
        with self._lock:
            self._adopt(body.get("status"))
            self._owner, self._lost_at = token_id, None
            current = dict(self._status) if self._status else {}
        if self._events is not None:
            self._events.publish("recording.started", severity="info", source="pilot_recording",
                                 data={"id": current.get("id"), "owner": token_id})
        return current

    def stop(self, token_id: str, *, is_admin: bool) -> dict:
        request = self.request_active
        with self._lock:
            status = self._fresh_status()
            owner = self._owner
        if request is None or status is None:
            raise _refused("RECORDER_UNAVAILABLE", "the camera unit's recorder is not reporting")
        if status["state"] != "recording":
            raise _refused("RECORDING_NOT_ACTIVE", "no recording is running")
        if owner != token_id and not is_admin:
            # An ownerless recording (CORE restarted mid-session) is an admin's to stop.
            raise RecordingRefused("FORBIDDEN", 403, "only the token that started it or an admin stops it")
        ok, message = request(False, True)
        body = self._reply(message)
        if not ok:
            raise _refused("RECORDER_UNAVAILABLE", "the recorder did not stop")
        with self._lock:
            self._adopt(body.get("status"))
            self._owner, self._lost_at = None, None
            current = dict(self._status) if self._status else {}
        self._stopped(status["id"], token_id, "operator")
        return current

    def fetched(self, recording_id: str) -> None:
        if self.publish_fetched is not None:
            self.publish_fetched(recording_id)

    # ------------------------------------------------------------ internals
    def _recording_owner(self) -> Optional[str]:
        status = self._fresh_status()
        if status is None or status["state"] != "recording":
            return None
        return self._owner

    def _check_link(self) -> None:
        with self._lock:
            owner = self._recording_owner()
            if owner is None or self._links.get(owner, 0) > 0:
                self._lost_at = None
                return
            now = self._clock()
            if self._lost_at is None:
                self._lost_at = now
            expired = now - self._lost_at >= LINK_GRACE_S
        if expired:
            self._stop_async("link_lost")

    def _stop_async(self, reason: str) -> None:
        with self._lock:
            status = self._fresh_status()
            if self._owner is None or status is None:
                return
            recording_id = status["id"]
            self._owner, self._lost_at = None, None
        request = self.request_active
        if request is not None:
            request(False, False)
        self._stopped(recording_id, None, reason)

    def _adopt(self, payload) -> None:
        """Caller holds the lock. A malformed reply keeps the last status."""
        try:
            status = RecorderStatus.model_validate(payload).model_dump(by_alias=True)
        except ValueError:
            return
        self._status, self._status_at = status, self._clock()

    @staticmethod
    def _reply(message: str) -> dict:
        try:
            body = json.loads(message or "{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _stopped(self, recording_id: Optional[str], by: Optional[str], reason: str) -> None:
        if self._events is not None:
            self._events.publish("recording.stopped", severity="info", source="pilot_recording",
                                 data={"id": recording_id, "by": by, "reason": reason})
