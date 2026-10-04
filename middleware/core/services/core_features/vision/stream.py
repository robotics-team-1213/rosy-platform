"""D-368 driver MJPEG stream gate. ROS-free; the route owns the transport.

The stream is the current teleop driver's alone (one open stream at a time).
There is no Pilot seat lease (D-460): the driver is the token of the most
recent accepted teleop, exactly the vocabulary the recording guard calls
``seat_changed`` (D-411 A). Ownership does not expire on a timer — the open
stream connection is itself the liveness proof, and a new accepted teleop from
another token switches the driver and evicts the previous stream.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import time


class StreamRefused(Exception):
    """Opening the stream failed. ``code`` maps to an HTTP status in the route."""

    STATUS = {"CAMERA_STREAM_NOT_DRIVER": 409, "CAMERA_STREAM_BUSY": 409}

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = self.STATUS.get(code, 409)


class DriverStreamGate:
    """One stream slot bound to the accepted-teleop driver."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._driver: Optional[str] = None
        self._driver_at: float = float("-inf")
        self._stream_token: Optional[str] = None
        #: accepted teleops seen; route failures never reach this class.
        self.hook_errors = 0

    # ------------------------------------------------------------- driver
    def on_teleop(self, token_id: str) -> None:
        """An accepted teleop. Last-wins; a new driver evicts the open stream."""
        token = str(token_id).strip()
        if not token:
            return
        with self._lock:
            if token == self._driver:
                return
            self._driver = token
            self._driver_at = self._clock()
            # The running generator ends on its next driver check; freeing the
            # slot here lets the new driver open without waiting for that.
            self._stream_token = None

    def driver(self) -> Optional[str]:
        with self._lock:
            return self._driver

    # ------------------------------------------------------------- stream
    def open(self, token_id: str) -> None:
        """Bind the single stream slot to ``token_id`` or refuse (D-368 §2)."""
        token = str(token_id).strip()
        with self._lock:
            if not token or token != self._driver:
                raise StreamRefused(
                    "CAMERA_STREAM_NOT_DRIVER",
                    "the live stream is reserved for the current teleop driver",
                )
            if self._stream_token is not None:
                raise StreamRefused(
                    "CAMERA_STREAM_BUSY",
                    "a driver camera stream is already open",
                )
            self._stream_token = token

    def close(self, token_id: str) -> None:
        """Release the slot. Idempotent; only the holder frees it."""
        token = str(token_id).strip()
        with self._lock:
            if self._stream_token == token:
                self._stream_token = None

    def stream_owner(self) -> Optional[str]:
        with self._lock:
            return self._stream_token

    def snapshot(self) -> dict:
        """Read model for tests and diagnostics; never identifies secrets."""
        with self._lock:
            return {
                "driver": self._driver,
                "driver_at": self._driver_at,
                "stream_open": self._stream_token is not None,
            }
