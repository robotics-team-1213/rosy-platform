"""Runner-owned native Gazebo pose for an explicitly bound simulation Fleet.

No ROS imports, transport, command writer, Vision sighting or operator pin. The
runner supplies actual stamped model-pose odometry, /clock and CORE snapshots.
Invalid continuity latches UNKNOWN; only a new bound run creates another port.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass

from rosy.world.state.projections.map_pose import MapPose, MapPoseConfig, odom_from_snapshot


@dataclass(frozen=True)
class NativeRobotBinding:
    robot_id: str
    model: str
    frame_id: str


@dataclass(frozen=True)
class NativeGazeboBinding:
    run_id: str
    epoch: int
    world: str
    map_id: str
    map_revision: int
    source_revision: str
    world_sha256: str
    graph_sha256: str
    urdf_sha256: str
    domain_id: int
    partition: str
    map_from_world: tuple[float, float, float]
    robots: tuple[NativeRobotBinding, ...]


@dataclass(frozen=True)
class NativeGazeboSample:
    binding: NativeGazeboBinding
    robot_id: str
    model: str
    frame_id: str
    stamp_ns: int
    pose: tuple[float, float, float]


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pose(value):
    return isinstance(value, tuple) and len(value) == 3 and all(_finite(v) for v in value)


def _angle(value):
    return math.atan2(math.sin(value), math.cos(value))


class NativeGazeboMapPosePort:
    simulation_only = True

    def __init__(self, binding: NativeGazeboBinding, *, gather_core,
                 wall=time.time, monotonic=time.monotonic):
        self._validate(binding)
        if not callable(gather_core):
            raise ValueError('native SIM pose requires actual CORE snapshot reader')
        self.binding, self.config = binding, MapPoseConfig()
        self._gather_core, self._wall, self._mono = gather_core, wall, monotonic
        self._robots = {robot.robot_id: robot for robot in binding.robots}
        self._samples, self._core, self._failed, self._refreshing = {}, {}, {}, {}
        self._history = {robot_id: deque() for robot_id in self._robots}
        self._clock = None
        self._active_map = None
        self._lock = threading.RLock()

    @staticmethod
    def _validate(binding):
        if not isinstance(binding, NativeGazeboBinding):
            raise ValueError('native SIM pose requires typed binding')
        for name in ('run_id', 'partition'):
            value = getattr(binding, name)
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
                raise ValueError(f'invalid native SIM {name}')
        if binding.world != 'map_v2_fleet' or binding.map_id != 'map_v2_fleet':
            raise ValueError('native SIM frame binding is scoped to map_v2_fleet')
        for name, length in (('source_revision', 40), ('world_sha256', 64),
                             ('graph_sha256', 64), ('urdf_sha256', 64)):
            if not re.fullmatch('[0-9a-f]{' + str(length) + '}', getattr(binding, name)):
                raise ValueError(f'invalid native SIM {name}')
        if (type(binding.domain_id) is not int or not 80 <= binding.domain_id <= 99
                or type(binding.epoch) is not int or binding.epoch < 1
                or type(binding.map_revision) is not int or binding.map_revision < 1
                or not _pose(binding.map_from_world)
                or not isinstance(binding.robots, tuple) or not binding.robots):
            raise ValueError('invalid native SIM domain/epoch/map/transform')
        ids, models = set(), set()
        for robot in binding.robots:
            if (not isinstance(robot, NativeRobotBinding)
                    or not re.fullmatch(r'rosy_\d{2}', robot.robot_id)
                    or robot.model != robot.robot_id or robot.frame_id != robot.robot_id + '/odom'
                    or robot.robot_id in ids or robot.model in models):
                raise ValueError('native SIM model/robot/frame must be bound one to one')
            ids.add(robot.robot_id); models.add(robot.model)

    def validate_simulation_binding(self, expected):
        """Check the separately supplied runner manifest, not a provider marker alone."""
        self._validate(self.binding)
        if json.dumps(expected, sort_keys=True) != json.dumps(asdict(self.binding), sort_keys=True):
            raise ValueError('native SIM provider differs from explicit runner binding')

    def bind_active_map(self, provider):
        """Fleet's active map revision must keep matching this immutable SIM run."""
        self._active_map = provider

    def knows(self, robot_id):
        return robot_id in self._robots

    def active_map_id(self):
        return self.binding.map_id

    def _fail(self, robot_id, reason):
        self._failed.setdefault(robot_id, reason)
        return False

    def observe_clock(self, stamp_ns):
        """Separate actual /clock callback. Replayed or reset clocks revoke this run."""
        with self._lock:
            now, wall = self._mono(), self._wall()
            if (type(stamp_ns) is not int or stamp_ns < 0
                    or (self._clock is not None and (stamp_ns <= self._clock[0]
                        or now < self._clock[1] or wall < self._clock[2]))):
                if self._clock is not None and not self._samples and type(stamp_ns) is int and stamp_ns >= 0:
                    self._clock = (stamp_ns, now, wall)   # a startup pause or restart: no pose to revoke yet
                    return True
                for robot_id in self._robots:
                    self._fail(robot_id, 'clock_reset_or_replay')
                return False
            self._clock = (stamp_ns, now, wall)
            return True

    @staticmethod
    def _ages(row, now, wall):
        # Native clock age is anchored at join; receipt age keeps its origin.
        return (max(now-row['received'], row['source_age'] + now-row['joined']),
                max(wall-row['wall'], row['source_age'] + wall-row['join_wall']))

    def observe(self, sample, *, clock_stamp_ns=None,
                received_wall=None, received_monotonic=None):
        """Admit a native measurement against the separately received live /clock.

        clock_stamp_ns, when supplied, only asserts the already observed clock;
        it cannot refresh the clock's receipt time. A runner buffering a future
        measurement must supply its original receipts, never the admission time.
        """
        with self._lock:
            if not isinstance(sample, NativeGazeboSample):
                for robot_id in self._robots:
                    self._fail(robot_id, 'invalid_native_sample')
                return False
            robot_id = sample.robot_id
            robot = self._robots.get(robot_id)
            if robot is None:
                return False
            if robot_id in self._failed:
                return False
            now, wall = self._mono(), self._wall()
            original_mono = now if received_monotonic is None else received_monotonic
            original_wall = wall if received_wall is None else received_wall
            if (not _finite(original_mono) or not _finite(original_wall)
                    or not 0 <= now-original_mono <= self.config.max_pair_s
                    or not 0 <= wall-original_wall <= self.config.max_pair_s):
                if _finite(original_mono) and _finite(original_wall) and original_mono <= now and original_wall <= wall:
                    return False   # rev 1: late under load, dropped; the pose reads UNKNOWN until a fresh one
                return self._fail(robot_id, 'invalid_native_receipt')
            if (not isinstance(sample, NativeGazeboSample) or sample.binding != self.binding
                    or sample.model != robot.model or sample.frame_id != robot.frame_id):
                return self._fail(robot_id, 'foreign_binding')
            if (type(sample.stamp_ns) is not int or sample.stamp_ns < 0 or not _pose(sample.pose)
                    or self._clock is None):
                return self._fail(robot_id, 'invalid_native_sample')
            clock, received, clock_wall = self._clock
            age = (clock - sample.stamp_ns) * 1e-9
            if (clock_stamp_ns is not None and clock_stamp_ns != clock
                    or not 0 <= now - received <= self.config.max_pair_s
                    or not 0 <= wall - clock_wall <= self.config.max_pair_s
                    or not 0 <= age <= self.config.max_pair_s):
                if clock_stamp_ns in (None, clock) and age >= 0:
                    return False   # rev 1: stale (a slow /clock or sample), dropped, not latched
                return self._fail(robot_id, 'native_clock_or_sample_stale')
            previous = self._samples.get(robot_id)
            if previous is not None:
                if (original_mono < previous['received'] or original_wall < previous['wall']):
                    return self._fail(robot_id, 'native_receipt_replay')
                # rev 1: a gap since the previous sample is not latched; the jump check below spans it by stamp
                old = previous['sample']; dt = (sample.stamp_ns - old.stamp_ns) * 1e-9
                distance = math.dist(sample.pose[:2], old.pose[:2])
                turn = abs(_angle(sample.pose[2] - old.pose[2]))
                if (dt <= 0 or distance > self.config.max_speed_mps * dt
                        or turn > math.radians(self.config.max_turn_rate_dps) * dt):
                    return self._fail(robot_id, 'native_reset_or_replay')
            self._samples[robot_id] = dict(sample=sample, received=original_mono,
                                          wall=original_wall, joined=now, join_wall=wall,
                                          source_age=age)
            history = self._history[robot_id]
            history.append((original_mono, sample.pose))
            since = now-self.config.max_odom_age_s
            while len(history) > 1 and history[1][0] < since:
                history.popleft()  # Keep the last before the window as its deadband base.
            return True

    async def refresh(self, robot_id, *, force_rest=False):
        if not self.knows(robot_id):
            return
        pending = self._refreshing.get(robot_id)
        if pending is None:
            pending = self._refreshing[robot_id] = asyncio.ensure_future(self._gather_core(robot_id))
        try:
            # A failed read keeps the last snapshot; _current still revokes it once it ages past max_odom_age_s.
            state = await asyncio.shield(pending)
        finally:
            if pending.done() and self._refreshing.get(robot_id) is pending:
                self._refreshing.pop(robot_id, None)
        with self._lock:
            core = odom_from_snapshot(state)
            previous = self._core.get(robot_id)
            if previous is None and core is None and isinstance(state, dict) and state.get('robot_id') == robot_id:
                return  # CORE has no odometry yet at startup: nothing to revoke, read again
            if (not isinstance(state, dict) or state.get('robot_id') != robot_id or core is None
                    or not 0 <= self._wall() - core.stamp <= self.config.max_odom_age_s
                    or (previous is not None and (core.stamp < previous.stamp
                        or (core.stamp == previous.stamp and core != previous)))):
                self._fail(robot_id, 'core_snapshot_invalid_or_stale')
                return
            self._core[robot_id] = core

    def _current(self, robot_id):
        if (self._active_map is not None
                and self._active_map() != (self.binding.map_id, self.binding.map_revision)):
            self._fail(robot_id, 'active_map_changed')
        row = self._samples.get(robot_id)
        core = self._core.get(robot_id)
        if row is None or core is None or robot_id in self._failed:
            return None
        now, wall = self._mono(), self._wall()
        elapsed = now - row['received']; wall_elapsed = wall - row['wall']
        native_ages = self._ages(row, now, wall)
        # Estimate capture against the join clock age, not original receipt minus
        # that age: the latter would subtract a buffered delay a second time.
        sample = row['sample']; captured_wall = row['join_wall'] - row['source_age']
        if (not 0 <= elapsed or not 0 <= wall_elapsed
                or now < row['joined'] or wall < row['join_wall']
                or math.dist((core.x, core.y), sample.pose[:2]) > self.config.max_jump_m
                or abs(_angle(core.yaw - sample.pose[2])) > math.radians(self.config.max_jump_deg)):
            self._fail(robot_id, 'native_or_core_stale_or_contradictory')
            return None
        if (max(native_ages) > self.config.max_pair_s
                or not 0 <= self._wall() - core.stamp <= self.config.max_odom_age_s
                or abs(core.stamp - captured_wall) > self.config.max_interp_gap_s):
            return None   # rev 1: stale under load reads UNKNOWN until fresh; not latched
        return row, core, max(native_ages)

    def arbitrated_pose(self, robot_id):
        with self._lock:
            if not self.knows(robot_id):
                return None
            current = self._current(robot_id)
            if current is None:
                return MapPose(None, None, None, 'UNKNOWN', 'native_gazebo_sim', 0., None,
                               map_id=self.binding.map_id, anchor_source='native_gazebo_sim')
            row, core, age = current
            x, y, yaw = row['sample'].pose; tx, ty, rotation = self.binding.map_from_world
            c, s = math.cos(rotation), math.sin(rotation)
            return MapPose(tx + c*x - s*y, ty + s*x + c*y, _angle(rotation + yaw),
                           'LOCALIZED', 'native_gazebo_sim', 0., age, anchor_age_s=age,
                           map_id=self.binding.map_id, odom_stamp=core.stamp,
                           anchor_source='native_gazebo_sim')

    def moved(self, robot_id, min_m, min_deg):
        """D-511 base/any-delta over the recent receipt-monotonic 3 s window."""
        with self._lock:
            current = self._current(robot_id)
            if current is None:
                return False
            history = self._history[robot_id]
            since = self._mono()-self.config.max_odom_age_s
            base = next((pose for at, pose in reversed(history) if at < since), history[0][1])
            return any(math.dist(pose[:2], base[:2]) > min_m
                       or abs(_angle(pose[2]-base[2])) > math.radians(min_deg)
                       for at, pose in history if at >= since)

    def diagnostics(self, robot_id):
        with self._lock:
            pose = self.arbitrated_pose(robot_id)
            row = self._samples.get(robot_id)
            return dict(binding=asdict(self.binding), state=pose.state if pose else None,
                        reason=self._failed.get(robot_id), epoch=self.binding.epoch,
                        native_stamp_ns=row['sample'].stamp_ns if row else None,
                        clock_stamp_ns=self._clock[0] if self._clock else None,
                        source_age_s=row['source_age'] if row else None,
                        receipt_age_s=self._mono()-row['received'] if row else None,
                        received_wall=row['wall'] if row else None,
                        received_monotonic=row['received'] if row else None,
                        joined_wall=row['join_wall'] if row else None,
                        joined_monotonic=row['joined'] if row else None,
                        receipt_wall_age_s=self._wall()-row['wall'] if row else None,
                        native_age_s=max(self._ages(row, self._mono(), self._wall())) if row else None,
                        core_odom_stamp=pose.odom_stamp if pose else None)
