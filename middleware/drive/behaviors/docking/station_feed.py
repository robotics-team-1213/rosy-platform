"""Session-bound station camera adapter; source epoch seconds become local monotonic evidence."""
from __future__ import annotations

import math
import threading

from core_common.protocol.station_charging import StationObservation
from .detector import DockObservation


class StationObservationFeed:
    def __init__(self, scope: StationObservation, *, clock, source_clock, max_age_s,
                 max_uncertainty_m, max_uncertainty_rad, marker_offset_m=0.0):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               or v <= 0 for v in (max_age_s, max_uncertainty_m, max_uncertainty_rad)):
            raise ValueError('STATION_OBSERVATION_LIMITS_REQUIRED')
        if (isinstance(marker_offset_m, bool) or not isinstance(marker_offset_m, (int, float))
                or not math.isfinite(marker_offset_m) or marker_offset_m < 0):
            raise ValueError('STATION_MARKER_OFFSET_INVALID')
        self.marker_offset_m = marker_offset_m
        self.scope, self.clock, self.source_clock = scope, clock, source_clock
        self.max_age_s = max_age_s
        self.max_uncertainty_m, self.max_uncertainty_rad = max_uncertainty_m, max_uncertainty_rad
        self._started, self._latest, self._deadline = None, None, None
        self._source = None
        self._sequence = -1
        self._lock = threading.RLock()

    def start(self, dock):
        with self._lock:
            if dock.id != self.scope.station_id:
                raise ValueError('STATION_TARGET_MISMATCH')
            self._started, self._latest, self._deadline = self.clock(), None, None
            self._source = None
            self._sequence = -1

    def ingest(self, observation: StationObservation, *, received_at: float) -> bool:
        with self._lock:
            self._latest, self._deadline = None, None
            self._source = None
            if self._started is None:
                return False
            try:
                source_now = self.source_clock()
                if not math.isfinite(received_at) or received_at < self._started or received_at > self.clock():
                    return False
                context = {key: getattr(self.scope, key) for key in (
                    'robot_id', 'station_id', 'session_id', 'boot_id', 'odom_epoch',
                    'map_id', 'map_revision', 'pose_revision', 'source_epoch', 'calibration_revision')}
                observation = StationObservation.model_validate(observation.model_dump(), context=context | {
                    'now': source_now})
                if observation.source_id != self.scope.source_id or observation.sequence <= self._sequence:
                    return False
                age = source_now - observation.captured_at
                at = received_at - age
                if (age > self.max_age_s or at < self._started
                        or observation.uncertainty_m > self.max_uncertainty_m
                        or observation.uncertainty_rad > self.max_uncertainty_rad):
                    return False
                self._sequence = observation.sequence
                if not observation.visible or observation.pose is None:
                    return False
                pose = observation.pose
                # Legacy confidence is a validity gate, not a claimed metric accuracy.
                # Metric acceptance uses the explicit uncertainty bounds above.
                # Parking consumes a marker beyond its seating target; the camera
                # contract instead locates that target itself. Preserve the target
                # by adding the same axial offset the parking controller subtracts.
                self._latest = DockObservation(
                    x=pose.x + self.marker_offset_m * math.cos(pose.yaw),
                    y=pose.y + self.marker_offset_m * math.sin(pose.yaw),
                    yaw=pose.yaw, at=at, confidence=1.0)
                self._deadline = min(at + self.max_age_s,
                                     received_at + (observation.valid_until - source_now))
                self._source = observation
                return True
            except (ValueError, TypeError):
                return False

    def relative_pose(self):
        with self._lock:
            sample = self._snapshot_locked()
            return sample[0] if sample is not None else None

    def relative_snapshot(self):
        """Pose and original remaining lease, converted conservatively to UTC."""
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self):
        source_now, local_now = self.source_clock(), self.clock()
        if self._latest is None or self._source is None:
            return None
        source_expiry = min(self._source.valid_until, self._source.captured_at+self.max_age_s)
        if (not self._latest.at <= local_now < self._deadline
                or not self._source.captured_at <= source_now < source_expiry):
            self._latest, self._source, self._deadline = None, None, None
            return None
        return self._latest, min(source_expiry, source_now+(self._deadline-local_now))

    def relative_pose_nowait(self):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            sample = self._snapshot_locked()
            return sample[0] if sample is not None else None
        finally:
            self._lock.release()

    def stop(self):
        with self._lock:
            self._started, self._latest, self._deadline = None, None, None
            self._source = None
