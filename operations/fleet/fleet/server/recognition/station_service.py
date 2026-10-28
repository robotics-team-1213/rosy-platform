"""Validate station candidates and robot acceptance; no ROS or motion commands."""
from __future__ import annotations

import math
import threading

from core_common.protocol.station_charging import StationPoseAck, StationPoseRecord


def _errors(left, right):
    return math.hypot(left.x - right.x, left.y - right.y), abs(
        math.atan2(math.sin(left.yaw - right.yaw), math.cos(left.yaw - right.yaw)))


class StationService:
    def __init__(self, store, *, clock, map_scope, trusted_sources, robot_scope, approach_validator,
                 position_tolerance_m, heading_tolerance_rad, max_uncertainty_m,
                 max_uncertainty_rad, consistency_samples):
        limits = (position_tolerance_m, heading_tolerance_rad, max_uncertainty_m, max_uncertainty_rad)
        if any(isinstance(v, bool) or not isinstance(v, (float, int))
               or not math.isfinite(v) or v <= 0 for v in limits):
            raise ValueError('INVALID_STATION_LIMITS')
        if type(consistency_samples) is not int or consistency_samples < 2:
            raise ValueError('STATION_CONSISTENCY_REQUIRED')
        self.store, self.clock, self.map_scope = store, clock, map_scope
        self.trusted_sources, self.robot_scope = dict(trusted_sources), robot_scope
        self.approach_validator = approach_validator
        self.position_tolerance_m, self.heading_tolerance_rad = position_tolerance_m, heading_tolerance_rad
        self.max_uncertainty_m, self.max_uncertainty_rad = max_uncertainty_m, max_uncertainty_rad
        self.consistency_samples = consistency_samples
        self._pending, self._acks = {}, {}
        self._lock = threading.RLock()

    def _context(self):
        map_id, map_revision = self.map_scope()
        return {'now': self.clock(), 'map_id': map_id, 'map_revision': map_revision}

    def _near(self, first, later):
        if any(getattr(first, key) != getattr(later, key) for key in (
                'map_id', 'map_revision', 'source_id', 'source_epoch', 'calibration_revision')):
            return False
        poses = [(first.pose, later.pose)]
        if first.approach_pose is not None and later.approach_pose is not None:
            poses.append((first.approach_pose, later.approach_pose))
        elif first.approach_pose != later.approach_pose:
            return False
        return all(distance <= self.position_tolerance_m and angle <= self.heading_tolerance_rad
                   for distance, angle in (_errors(left, right) for left, right in poses))

    def observe(self, candidate: StationPoseRecord) -> StationPoseRecord | None:
        with self._lock:
            candidate = StationPoseRecord.model_validate(candidate.model_dump(), context=self._context())
            trusted = self.trusted_sources.get(candidate.source_id)
            if candidate.status != 'CANDIDATE' or trusted != (candidate.source_epoch, candidate.calibration_revision):
                raise ValueError('STATION_SOURCE_NOT_VERIFIED')
            if (candidate.uncertainty_m > self.max_uncertainty_m
                    or candidate.uncertainty_rad > self.max_uncertainty_rad):
                raise ValueError('STATION_OBSERVATION_UNCERTAIN')
            current = self.store.get(candidate.station_id)
            if current is not None and current.status == 'VALID':
                if candidate.captured_at <= current.captured_at:
                    return None
                if self._near(current, candidate) and current.valid_until > self.clock():
                    distance, angle = _errors(current.pose, candidate.pose)
                    uncertainty = max(current.uncertainty_m, candidate.uncertainty_m + distance)
                    angular = max(current.uncertainty_rad, candidate.uncertainty_rad + angle)
                    if uncertainty <= self.max_uncertainty_m and angular <= self.max_uncertainty_rad:
                        return self.store.refresh(candidate.model_copy(update={
                            'uncertainty_m': uncertainty, 'uncertainty_rad': angular}),
                            expected_revision=current.pose_revision)
                self.store.invalidate(current.station_id, expected_revision=current.pose_revision,
                                      reason='STATION_REVALIDATION_REQUIRED')
                self._acks = {key: ack for key, ack in self._acks.items() if ack.station_id != current.station_id}
            pending = self._pending.get(candidate.station_id)
            if pending is not None:
                first, last_at, count = pending
                if candidate.captured_at <= last_at:
                    return None
                if self._near(first, candidate) and first.valid_until > self.clock():
                    count += 1
                else:
                    first, count = candidate, 1
            else:
                first, count = candidate, 1
            self._pending[candidate.station_id] = first, candidate.captured_at, count
            if (count < self.consistency_samples or candidate.approach_pose is None
                    or not self.approach_validator(candidate)):
                return None
            candidate = candidate.model_copy(update={'approach_verified': True})
            proposed = self.store.propose(candidate)
            confirmed = self.store.confirm(proposed.station_id, expected_revision=proposed.pose_revision)
            del self._pending[candidate.station_id]
            return confirmed

    def accept_ack(self, ack: StationPoseAck) -> bool:
        with self._lock:
            try:
                record = self.store.get(ack.station_id)
                if record is None or record.status != 'VALID' or not ack.accepted:
                    return False
                StationPoseRecord.model_validate(record.model_dump(), context=self._context())
                scope = self.robot_scope(ack.robot_id)
                if scope is None:
                    return False
                StationPoseAck.model_validate(ack.model_dump(), context=self._context() | {
                    'boot_id': scope[0], 'session_id': scope[1], 'pose_revision': record.pose_revision})
                if ack.captured_at < record.captured_at:
                    return False
                self._acks[(ack.robot_id, ack.station_id)] = ack
                return True
            except ValueError:
                return False

    def ready_for_return(self, robot_id: str, station_id: str) -> StationPoseRecord | None:
        with self._lock:
            ack = self._acks.get((robot_id, station_id))
            if ack is None:
                return None
            # Recheck current boot/session, map, installation and both evidence leases each time.
            try:
                record = self.store.get(station_id)
                if record is None or record.status != 'VALID':
                    return None
                StationPoseRecord.model_validate(record.model_dump(), context=self._context())
                scope = self.robot_scope(robot_id)
                if scope is None:
                    return None
                StationPoseAck.model_validate(ack.model_dump(), context=self._context() | {
                    'boot_id': scope[0], 'session_id': scope[1], 'pose_revision': record.pose_revision})
                return record
            except ValueError:
                return None

    def installations(self) -> list[StationPoseRecord]:
        """Stored validity is historical; current readback also applies map and time validity."""
        result = []
        for record in self.store.list():
            try:
                StationPoseRecord.model_validate(record.model_dump(), context=self._context())
            except ValueError:
                record = record.model_copy(update={'status': 'INVALID'})
            result.append(record)
        return result
