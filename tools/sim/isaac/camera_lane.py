"""D-650: frozen existing perception and CORE line-follow, simulation only."""
import bisect
from dataclasses import replace
import math
import time
from types import SimpleNamespace

import numpy as np

from control.sensing.perception.camera_visibility import visibility_reason
from control.sensing.perception.drivable.drivable_keep import keep_step, scan_summary
from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from control.sensing.perception.lane import LaneObservation
from control.sensing.perception.lane_keep import LaneKeeper, clean_learned_mask
from control.sensing.perception.lane_containment import containment_payload
from control.sensing.perception.learned.drivable_paint import boundary_paint, lateral_px_per_m
from control.sensing.perception.learned.paint_motion import OdomHistory
from control.sensing.perception.learned.paint_worker import LearnedPaintWorker
from core_events.events.bus import EventBus
from core_common.protocol.lane_containment import LaneContainmentEvidence
from core.bridge.observation import front_clearance
from core_features.line_follow import LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation
from core_features.line_follow.clearance import return_scan_view
from map_task import QPolicy, SIM_DEVICE_IDS


def camera_model_identity(model, *, revision, sha256):
    manifest = model.manifest
    roles = {c.role for c in manifest.classes}
    chosen = [f for f in manifest.files if f.name == manifest.onnx_file().name]
    if (manifest.backend != 'onnx' or manifest.model_revision != revision
            or not {'lane_marking', 'drivable'} <= roles or len(chosen) != 1 or chosen[0].sha256 != sha256):
        raise ValueError('existing camera model revision/hash/roles differ')
    identity = {'schema': 'isaac-camera-error-confidence/2', 'model_revision': revision, 'model_sha256': sha256}
    CameraQPolicy(17, perception=identity)
    return identity


class CameraQPolicy(QPolicy):
    def __init__(self, seed, *, perception):
        super().__init__(seed)
        if (not isinstance(perception, dict) or set(perception) != {'schema', 'model_revision', 'model_sha256'}
                or perception['schema'] != 'isaac-camera-error-confidence/2'
                or not isinstance(perception['model_revision'], str) or not perception['model_revision']
                or not isinstance(perception['model_sha256'], str) or len(perception['model_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in perception['model_sha256'])):
            raise ValueError('pinned camera observation and model identity required')
        self.perception = dict(perception)

    def export(self):
        return {**super().export(), 'perception': dict(self.perception)}

    @classmethod
    def restore(cls, data, *, perception):
        if not isinstance(data, dict) or set(data) != {'updates', 'gains', 'q', 'perception'}:
            raise ValueError('camera policy required; path policy refused')
        policy = cls(17, perception=perception)
        if data['perception'] != policy.perception:
            raise ValueError('camera policy observation/model identity differs')
        restored = QPolicy.restore({key: data[key] for key in ('updates', 'gains', 'q')})
        policy.table, policy.updates = restored.table, restored.updates
        return policy


class CameraLineManager(LineFollowManager):
    def __init__(self, *, config, clock, device_id='isaac-pinky'):
        if type(device_id) is not str or device_id not in SIM_DEVICE_IDS:
            raise ValueError('fixed simulation device identity required')
        super().__init__(EventBus(device_id), config=config, clock=clock)
        self._baseline_gain = config.steering_gain

    def tick_gain(self, now, *, gain):
        if type(gain) not in (int, float) or gain not in QPolicy.gains:
            raise ValueError('bounded camera yaw gain required')
        # Simulation instrumentation: the same lock/tick checks the learned intended sweep and all gates.
        with self._lock:
            self._config = replace(self._config, steering_gain=self._baseline_gain * gain)
            return self.tick(now)


class LearnedCameraLane:
    def __init__(self, model, ground, *, camera_x, clock=time.monotonic, config=None,
                 device_id='isaac-pinky', body=None):
        if ground is None or not math.isfinite(camera_x):
            raise ValueError('configured native ground and camera position required')
        self.ground, self.camera_x, self.clock = ground, camera_x, clock
        config = config or LineFollowConfig(
            cruise_speed=.04, max_linear=.06, steering_gain=.4, max_angular=.8,
            lost_auto_resume=False)
        self.native_body = body
        if body is not None:
            config = replace(config, obstacle_mode='path', body_front_x_m=body.front_x_m,
                body_rear_x_m=body.rear_x_m, body_half_width_m=body.half_width_m,
                body_rotation_radius_m=body.rotation_radius_m, body_lidar_x_m=body.lidar_x_m,
                lidar_forward_deg=body.lidar_forward_deg)
        self.manager = CameraLineManager(config=config, clock=clock, device_id=device_id)
        self.manager.set_mode(LineFollowMode.CAMERA_LINE)
        self.worker = LearnedPaintWorker(SimpleNamespace(poll=lambda: model), clock=clock,
                                         start=False, target='drivable')
        self.keeper = LaneKeeper(camera_x_offset_m=camera_x)
        self.steer, self.history = DrivableSteer.from_config(vars(config)), OdomHistory()
        self.frame, self.stamp, self.received_at = 0, None, None
        self.observation = None
        self.wall, self.scan_stamp_ns = None, None
        self.last = {'model_used': False, 'reason': 'no_camera_frame'}

    def observe_scan(self, sample, *, body):
        if self.native_body is not None and body != self.native_body:
            raise ValueError('native scan and CORE body geometry differ')
        received_at = self.clock()
        evidence = return_scan_view(sample, body=body,
            source_now_ns=sample.get('source_now_ns'), clearance_horizon_m=.35)
        if (evidence is None or (self.scan_stamp_ns is not None
                                and evidence[2] <= self.scan_stamp_ns)):
            self.wall = None
            self.manager.observe_return_scan(None, source_age_s=None, source_stamp_ns=None,
                                             received_at=received_at)
            self.invalidate('native_scan_unavailable')
            return False
        view, age, stamp_ns = evidence
        front_clearance(SimpleNamespace(loc_mission=None, line_follow=self.manager),
                        sample, received_at=received_at)
        if not self.manager.wants_return_scan:
            self.manager.observe_return_scan(view, source_age_s=age, source_stamp_ns=stamp_ns,
                                             received_at=received_at)
        if self.native_body is not None and view.unknown:
            self.wall = None
            self.invalidate('native_scan_unknown')
            return False
        ahead, sides, front = scan_summary(sample['ranges'], sample['angle_min'], sample['angle_increment'],
                                           sample['range_min'], sample['range_max'], body=body)
        self.wall, self.scan_stamp_ns = (ahead, stamp_ns / 1e9, sides, front), stamp_ns
        return True

    def invalidate(self, reason):
        self.manager.invalidate(self.clock())
        self.worker.reset()
        self.keeper.reset()
        self.steer.reset()
        self.observation = None
        self.frame = 0
        self.last = {'model_used': False, 'reason': reason, 'inference_error': self.worker.last_error}

    def observe(self, bgr, *, stamp, source_now, pose, guide=None):
        captured_at = self.clock()
        if (type(stamp) not in (int, float) or type(source_now) not in (int, float)
                or not math.isfinite(stamp) or not math.isfinite(source_now)
                or not 0 <= source_now - stamp <= self.manager.config.stale_after_s
                or (self.stamp is not None and stamp <= self.stamp)):
            self.invalidate('camera_source_stale')
            return
        self.stamp = stamp
        if (not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8
                or bgr.ndim != 3 or bgr.shape[2] != 3 or min(bgr.shape[:2]) < 8):
            self.invalidate('invalid_camera_image')
            return
        quality = visibility_reason(bgr)
        if quality != 'usable':
            self.invalidate(quality)
            return
        if len(pose) != 3 or not all(math.isfinite(v) for v in pose):
            self.invalidate('invalid_camera_odometry')
            return
        self.history.add(stamp, *pose)
        self.manager.observe_return_pose(stamp_ns=round(stamp * 1e9),
            source_now_ns=round(source_now * 1e9), frame='odom',
            x=pose[0], y=pose[1], yaw=pose[2], received_at=captured_at)
        # Compare in the native scan's nanoseconds to avoid a rounding-induced future sample.
        if self.wall is not None and not 0 <= round(source_now * 1e9) - self.scan_stamp_ns <= 250_000_000:
            self.invalidate('native_scan_stale')
            return
        pose_at = lambda when: pose if when == stamp else self.history.pose_at(when)
        self.worker.submit(bgr, tag=self.frame, stamp=stamp)
        self.worker.step()
        mask = self.worker.mask_for(bgr, every_n=1, stamp=stamp,
            clean=lambda m: clean_learned_mask(m, self.ground.horizon_row),
            clean_drivable=lambda way: clean_learned_mask(boundary_paint(
                way > 0, lateral_px_per_m(np.arange(way.shape[0]), focal_px=self.ground.focal_px,
                    principal_y=self.ground.principal_y, pitch_rad=self.ground.pitch_rad,
                    height_m=self.ground.height_m), .015), self.ground.horizon_row))
        # mask_for queues the current frame; the next explicit submit replaces it, so inference stays once/frame.
        self.frame += 1
        if self.worker.last_error or mask is None:
            self.invalidate('learned_camera_unavailable')
            return
        observation = self.keeper.update(bgr, self.ground, paint_mask=mask,
            crosswalk_mask=self.worker.used_crosswalk, lane_half_width_m=.0925)
        step, decided = keep_step(self.steer, self.worker, self.keeper.last, self.ground,
            self.camera_x, .0925, pose_at, stamp, self.wall, guide)
        provenance = 'model_lane_mask'
        if decided:
            info = self.keeper.last.get('drivable_steer', {})
            strategy = self.keeper.last.get('strategy', '')
            creep_target = info.get('observed_creep_target_m')
            if info.get('target_now_m') and (strategy == 'drivable_centre'
                    or strategy.startswith('drivable_turn_')):
                provenance = 'observed_target'
            elif (strategy == 'drivable_creep' and info.get('observed_creep_key') == stamp
                    and not any(info.get(key) for key in ('switch_pending', 'exit_from_memory', 'exit_behind_line'))
                    and isinstance(creep_target, (tuple, list)) and len(creep_target) == 2
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in creep_target)
                    and creep_target[0] > 0):
                provenance = 'observed_creep'
            elif (strategy.startswith('drivable_off_line_') and info.get('target_m')
                    and strategy == 'drivable_off_line_' + str(info.get('straddle'))):
                provenance = 'observed_straddle'
            elif (strategy == 'expected_path_held' and self.keeper.last.get('expected_path_state') == 'held'
                    and self.keeper.last.get('target_m') and self.keeper.last.get('expected_path_m')):
                provenance = 'odom_expected_path'
            else:
                self.invalidate('camera_target_unavailable')
                self.last['strategy'] = strategy
                self.last['camera_target'] = {key: info.get(key) for key in
                    ('target_m', 'target_now_m', 'ahead_m', 'guided', 'guide_deg', 'straddle',
                     'reason', 'exit', 'seen_exit', 'exit_behind_line', 'side_clear_m',
                     'reorient_deferred', 'pivot_limit', 'exit_from_memory', 'centre_path_m',
                     'near_centre_m', 'wall_ahead_m', 'observed_creep_key',
                     'observed_creep_target_m', 'switch_pending')}
                return
            observation = None if step is None else LaneObservation(*step)
        now = self.clock()
        if not 0 <= source_now - stamp + now - captured_at <= self.manager.config.stale_after_s:
            self.invalidate('camera_processing_stale')
            return
        containment = containment_payload(self.keeper.last, self.ground, stamp=stamp,
            source='ISAAC', camera_x=self.camera_x,
            crosswalk_uncertainty=self.worker.used_crosswalk is not None)
        accepted = self.manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, stamp,
            observation is not None, None if observation is None else observation.error,
            0. if observation is None else observation.confidence,
            containment=LaneContainmentEvidence.model_validate(containment)),
            received_at=captured_at, source_now=source_now)
        self.observation = observation if accepted else None
        self.received_at = captured_at if accepted else None
        self.last = {'model_used': True, 'model_revision': self.worker.used_model_revision,
                     'containment': containment,
                     'camera_provenance': provenance,
                     'paint_kind': self.worker.used_paint_kind, 'inference_error': None,
                     'speed_bump_pixels': (None if self.worker.used_speed_bump is None
                                           else int(np.count_nonzero(self.worker.used_speed_bump))),
                     'source_stamp': stamp, 'received_at': captured_at, 'processing_s': now - captured_at,
                     'source_age_s': source_now - stamp,
                     'reason': self.keeper.last.get('reason'),
                     'strategy': self.keeper.last.get('strategy'),
                     'error': None if self.observation is None else self.observation.error,
                     'confidence': 0. if self.observation is None else self.observation.confidence}

    def current(self):
        if self.observation is None or self.received_at is None or not self.last.get('model_used'):
            return False
        elapsed = self.clock() - self.received_at
        return 0 <= elapsed <= self.manager.config.stale_after_s - self.last['source_age_s']

    def state(self):
        if not self.current() or self.last.get('camera_provenance') == 'odom_expected_path':
            return None
        error, confidence = self.observation.error, self.observation.confidence
        return (bisect.bisect_right((-.6, -.2, -.05, .05, .2, .6), error),
                bisect.bisect_right((.35, .8), confidence))

    def close(self):
        self.manager.stop()
        self.worker.close()
