"""Settle -> freeze AE/AWB step of camera_detect_node. A mixin on CameraDetectNode; it reads the
node's parameters and state (_locked, _settle_deadline, _lock_attempts, _cam, ...)."""
import time

from .sensing.perception.camera_controls import lock_action, lock_controls, lock_summary
from .sensing.perception.v4l2_controls import v4l2_lock_summary


class CameraLockMixin:
    def _maybe_lock(self):
        """Freeze AE/AWB once they have settled.

        The floor reference cannot mean anything while the ISP is still
        re-deciding gains underneath it: measured, a 1.3x gain step on one
        unchanged frame flips blocked, and a white-balance shift flips the whole
        near band. Bounded retries so one bad metadata read at the settle instant
        does not disable the lock for the session; after that, stay in auto and
        say so rather than freezing on a value we do not trust.
        """
        if self._locked is not None:
            return
        action = lock_action(bool(self.get_parameter('camera_lock_enabled').value),
                             time.monotonic(), self._settle_deadline, self._lock_attempts)
        if action == 'wait':
            return
        if action == 'disabled':
            self._announce_lock('auto (lock disabled by parameter)', froze=False)
            return
        if action == 'exhausted':
            self._announce_lock('auto (lock unavailable after '
                                f'{self._lock_attempts} attempts)', froze=False)
            return
        settle = max(0.0, float(self.get_parameter('camera_settle_seconds').value))
        if hasattr(self._cam, 'freeze_controls'):
            controls = self._cam.freeze_controls()
            if controls:
                self._announce_lock(v4l2_lock_summary(controls))
                return
            self._lock_attempts += 1
            self._settle_deadline = time.monotonic() + max(0.5, settle)
            return
        try:
            controls = lock_controls(self._cam.capture_metadata())
        except Exception as exc:
            self.get_logger().warn(f'camera metadata unreadable: {exc}')
            controls = None
        if controls:
            try:
                self._cam.set_controls(controls)
            except Exception as exc:
                self.get_logger().warn(f'camera lock rejected: {exc}')
                controls = None
        if controls is None:
            self._lock_attempts += 1
            self._settle_deadline = time.monotonic() + max(0.5, settle)
            return
        self._announce_lock(lock_summary(controls))
