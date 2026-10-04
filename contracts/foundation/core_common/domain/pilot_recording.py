"""D-411 A: CORE's Pilot recording guard. ROS-free; ros_bridge wires the transport.

CORE only asks the camera unit's recorder to start or stop. It stops a recording when the
owner's /ws/state link is gone for LINK_GRACE_S, or when another token's teleop is accepted.
CORE has no Pilot seat, so "link" is the owner token's open /ws/state sockets and "seat
change" is an accepted teleop from another token. Both are judged on each recorder status
(1 Hz) and on each accepted teleop; no timer of its own. The link grace only applies once
the owner has opened a /ws/state link: a REST-only owner is ended by the recorder's 600 s cap.

request_active(on, wait) -> (ok, message): the bridge's SetBool call. message is the
recorder's {"code", "status"} JSON. Stops the guard decides itself use wait=False: they
run on executor callbacks, where waiting for a service reply would deadlock. Such a stop is
announced (recording.stopped) only when the recorder's status confirms it.

Statuses carry (boot_id, seq): one older than the newest adopted from the same boot (a late
`idle` published before a start, delivered after it) is dropped.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

from core_common.protocol.recording import ACTIVE_STATES, STOPPABLE_STATES, RecorderStatus

STATUS_STALE_S = 3.0
LINK_GRACE_S = 5.0
#: An unconfirmed guard stop is asked again after this long.
STOP_RETRY_S = 3.0
_REFUSAL_STATUS = {"RECORDING_BUSY": 409, "RECORDING_QUOTA_FULL": 507, "RECORDING_DISK_FULL": 507,
                   "RECORDING_NOT_ACTIVE": 409, "RECORDER_UNAVAILABLE": 503}
_ACTIVE = ACTIVE_STATES
_STOPPABLE = STOPPABLE_STATES   # `starting` counts: the writer is already running
_log = logging.getLogger(__name__)


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
        self._owner_linked = False
        self._links: dict[str, int] = {}
        self._lost_at: Optional[float] = None
        #: (reason, asked_at) of a guard stop the recorder has not confirmed yet.
        self._pending: Optional[tuple[str, float]] = None
        #: The recording whose recording.stopped is already out (one announcement each).
        self._announced: Optional[str] = None
        #: Guard stops that could not be sent (refused or raised). Never raised to callers.
        self.async_stop_failures = 0
        #: Failures of the teleop hook in the API (counted there, never a 500).
        self.hook_errors = 0
        #: (on, wait) -> (ok, message). None until the ROS bridge is wired.
        self.request_active: Optional[Callable[[bool, bool], tuple[bool, str]]] = None
        self.request_start: Optional[Callable[[str, bool], tuple[bool, str]]] = None
        self.start_available: Optional[Callable[[], bool]] = None
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

    def preview_modes(self) -> list[str]:
        """Advertise the typed option only while its installed route is ready."""
        if self.status() is None:
            return []
        if self.request_start is not None and self.start_available is not None and self.start_available():
            return ['raw', 'annotated']
        return ['raw'] if self.request_active is not None else []

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
            if not self._adopt(status):
                return
            was_active = previous is not None and previous["state"] in _ACTIVE
            if status["state"] not in _ACTIVE and (self._owner is not None or (
                    was_active and previous["id"] != self._announced)):
                # Owned, or ownerless after a CORE restart: either way the end is audited once.
                reason = self._pending[0] if self._pending else (
                    status["last_stop_reason"] or "recorder_exit")
                ended = (previous["id"] if previous else None, reason)
                self._clear_owner()
            pending = self._pending[0] if self._pending else None
        if ended is not None:
            self._stopped(ended[0], None, ended[1])
            return
        if pending is not None:
            self._stop_async(pending)       # re-sent once STOP_RETRY_S passed unconfirmed
        self._check_link()

    def link_opened(self, token_id: str) -> None:
        with self._lock:
            self._links[token_id] = self._links.get(token_id, 0) + 1
            if token_id == self._owner:
                self._owner_linked, self._lost_at = True, None

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
    def start(self, token_id: str, *, preview_mode: str = 'raw') -> dict:
        if preview_mode not in ('raw', 'annotated'):
            raise RecordingRefused('INVALID_RECORDING_OPTIONS', 422, 'unknown preview mode')
        typed = (self.request_start is not None and self.start_available is not None
                 and self.start_available())
        request = self.request_start if typed else self.request_active if preview_mode == 'raw' else None
        with self._lock:
            status = self._fresh_status()
        if request is None or status is None:
            raise _refused("RECORDER_UNAVAILABLE", "the camera unit's recorder is not reporting")
        if status["state"] in _ACTIVE:
            raise _refused("RECORDING_BUSY", "a recording is running or still being finished")
        ok, message = request(preview_mode if typed else True, True)
        body = self._reply(message)
        if not ok:
            code = body.get("code") or "RECORDER_UNAVAILABLE"
            raise _refused(code, f"the recorder refused to start: {code}")
        try:
            actual = RecorderStatus.model_validate(body.get('status')).model_dump(by_alias=True)
            if actual['state'] not in _ACTIVE or actual.get('preview_mode', 'raw') != preview_mode:
                raise ValueError('recording start option was not confirmed')
        except (TypeError, ValueError) as exc:
            # A malformed success must not become an owned recording with invented options.
            if self.request_active is not None:
                try:
                    self.request_active(False, False)
                except Exception:  # noqa: BLE001 - best-effort cleanup, preserve the refusal
                    _log.exception('pilot recorder option mismatch cleanup failed')
            raise _refused('RECORDER_UNAVAILABLE', 'recorder did not confirm the start options') from exc
        with self._lock:
            self._adopt_reply(body.get("status"))
            self._owner, self._lost_at, self._pending = token_id, None, None
            self._owner_linked = self._links.get(token_id, 0) > 0
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
        if status["state"] not in _STOPPABLE:
            raise _refused("RECORDING_NOT_ACTIVE", "no recording is running")
        # An ownerless recording (CORE restarted mid-session) is any operator's to stop.
        if owner not in (None, token_id) and not is_admin:
            raise RecordingRefused("FORBIDDEN", 403, "only the token that started it or an admin stops it")
        ok, message = request(False, True)
        body = self._reply(message)
        if not ok:
            raise _refused("RECORDER_UNAVAILABLE", "the recorder did not stop")
        with self._lock:
            self._adopt_reply(body.get("status"))
            self._clear_owner()
            current = dict(self._status) if self._status else {}
        self._stopped(status["id"], token_id, "operator")
        return current

    def fetched(self, recording_id: str) -> None:
        if self.publish_fetched is not None:
            self.publish_fetched(recording_id)

    # ------------------------------------------------------------ internals
    def _recording_owner(self) -> Optional[str]:
        status = self._fresh_status()
        if status is None or status["state"] not in _STOPPABLE:
            return None
        return self._owner

    def _check_link(self) -> None:
        with self._lock:
            owner = self._recording_owner()
            if owner is None or not self._owner_linked or self._links.get(owner, 0) > 0:
                self._lost_at = None
                return
            now = self._clock()
            if self._lost_at is None:
                self._lost_at = now
            expired = now - self._lost_at >= LINK_GRACE_S
        if expired:
            self._stop_async("link_lost")

    def _stop_async(self, reason: str) -> None:
        """Ask without waiting; recording.stopped follows the recorder's confirming status."""
        with self._lock:
            if self._recording_owner() is None:
                return
            now = self._clock()
            if self._pending is not None and now - self._pending[1] < STOP_RETRY_S:
                return
            self._pending = (reason, now)
        request = self.request_active
        try:
            sent = request is not None and request(False, False)[0]
        except Exception:  # noqa: BLE001 - a transport fault must not reach teleop or a ROS callback
            _log.exception("pilot recording: %s stop could not be sent", reason)
            sent = False
        if not sent:
            self.async_stop_failures += 1
            _log.warning("pilot recording: %s stop refused; asking again on the next check", reason)
            with self._lock:
                self._pending = None

    def _clear_owner(self) -> None:
        """Caller holds the lock."""
        self._owner, self._owner_linked, self._lost_at, self._pending = None, False, None, None

    def _adopt(self, status: dict) -> bool:
        """Caller holds the lock. False for a status older than the adopted one (same boot)."""
        previous = self._status
        if (previous is not None and status["seq"] > 0 and previous["seq"] > 0
                and status["boot_id"] == previous["boot_id"] and status["seq"] <= previous["seq"]):
            return False
        self._status, self._status_at = status, self._clock()
        return True

    def _adopt_reply(self, payload) -> None:
        """Caller holds the lock. A malformed reply keeps the last status."""
        try:
            status = RecorderStatus.model_validate(payload).model_dump(by_alias=True)
        except ValueError:
            return
        self._adopt(status)

    @staticmethod
    def _reply(message: str) -> dict:
        try:
            body = json.loads(message or "{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _stopped(self, recording_id: Optional[str], by: Optional[str], reason: str) -> None:
        with self._lock:
            self._announced = recording_id
        if self._events is not None:
            self._events.publish("recording.stopped", severity="info", source="pilot_recording",
                                 data={"id": recording_id, "by": by, "reason": reason})
