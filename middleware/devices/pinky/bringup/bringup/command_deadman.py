"""Driver-side stale ``cmd_vel`` protection independent of ``core``."""

from __future__ import annotations

import time
from collections.abc import Callable


class CommandDeadman:
    """Require a confirmed stop when an armed command stream becomes stale."""

    def __init__(
        self,
        timeout_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._timeout_s = float(timeout_s)
        self._clock = clock
        self._last_command_at = 0.0
        self._armed = False

    def mark_command(self) -> None:
        self._last_command_at = self._clock()
        self._armed = True

    def should_stop(self) -> bool:
        if not self._armed:
            return False
        return self._clock() - self._last_command_at >= self._timeout_s

    def mark_stopped(self) -> None:
        """Disarm only after the driver accepted a zero-RPM command."""
        self._armed = False

    def mark_stop_required(self) -> None:
        """Arm an immediate retry when a zero-RPM command was not confirmed."""
        self._last_command_at = self._clock() - self._timeout_s
        self._armed = True

    def attempt_stop(self, stop_command: Callable[[], bool]) -> bool | None:
        """Try an expired stop, preserving expiry when the driver rejects it."""
        if not self.should_stop():
            return None
        stopped = bool(stop_command())
        if stopped:
            self.mark_stopped()
        return stopped
