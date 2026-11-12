#!/usr/bin/env python3
"""Publish normalized white-line evidence from IR reflectance or camera frames."""

import json
import math

import cv2
import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image, LaserScan
from std_msgs.msg import String, UInt16MultiArray

from . import executor_choice
from .calibrated_values import calibrated
from .core_law_input import configure_drivable_law, refresh_drivable_law
from .lane_route_guide_input import LaneRouteGuideInput, subscribe_route_guide
from .line_observer_helpers import LineObserverHelpersMixin, build_ir_calibration, encode_debug_overlay_msg, load_nominal_camera_profile
from .route_context_input import RouteContextInput, bend_expected
from .route_followers import RouteFollowerInput
from .sensing.perception.camera_visibility import visibility_reason
from .sensing.perception.drivable.drivable_keep import keep_step, scan_summary
from .sensing.perception.evidence_mode import EvidenceModes
from .sensing.perception.lane_containment import PAINT_HALF_WIDTH_M, containment_payload, geometry_error, paint_half_width
from .sensing.perception.lane_debug import keep_debug_payload, next_publish_due, render_debug
from .sensing.perception.learned.paint_motion import OdomHistory, mask_homography, warp_mask
from perception_runtime.keep_odom_veto import OdomVetoLaneKeeper
from perception_runtime.perception.camera_ground import nominal_ground_plane, simulation_ground_allowed, simulation_ground_plane
from perception_runtime.perception.image_frame import image_msg_to_frame
from perception_runtime.perception.lane import (
    IRLineCalibration, LaneBetweenKeeper, LaneCornerTracker, LaneObservation,
    detect_ir_line, detect_lane_centre, detect_lane_error, line_observation_payload,
)
from perception_runtime.perception.lane_bev import LaneEdgeFollower, pose_if_fresh
from perception_runtime.perception.lane_boundaries import LaneBoundaryTracker
from perception_runtime.perception.lane_keep import LaneKeeper, clean_learned_mask, denoise_white_mask
from perception_runtime.perception.lane_keep_lines import HORIZON_MARGIN_PX, drop_small_components, floor_pink_mask
from perception_runtime.perception.learned.drivable_paint import boundary_paint, lateral_px_per_m

_READ_ONLY = ParameterDescriptor(read_only=True)
KEEP_MAX_FRAME_GAP_S = 0.5
COMMANDED_PIVOT_LINEAR_MPS = 1e-3
KEEP_CMD_STALE_WARN_FRAMES = 30


def _spinning_in_place(twist):
    return twist is not None and abs(twist[1]) > 0.15 and abs(twist[0]) < COMMANDED_PIVOT_LINEAR_MPS


class LineObserverNode(LineObserverHelpersMixin, Node, RouteFollowerInput):
    def __init__(self):
        super().__init__('line_observer_node')
        self.declare_parameter('ir_calibration_enabled', False)
        self.declare_parameter('ir_black', [0.0, 0.0, 0.0])
        self.declare_parameter('ir_white', [0.0, 0.0, 0.0])
        self.declare_parameter('ir_min_span', 100.0)
        self.declare_parameter('ir_min_white', 0.55)
        self.declare_parameter('ir_min_contrast', 0.15)
        self.declare_parameter('camera_bright_threshold', 180)
        self.declare_parameter('camera_roi_top_fraction', 0.4)
        self.declare_parameter('camera_washed_fraction', 0.4)
        self.declare_parameter('camera_min_pixels', 80)
        self.declare_parameter('require_camera_controls_stable', True)
        self.declare_parameter('paint_source', 'threshold', _READ_ONLY)
        self.declare_parameter('learned_lane_pointer', '', _READ_ONLY)
        self.declare_parameter('learned_paint_target', 'lane_marking', _READ_ONLY)
        self.declare_parameter('learned_paint_stale_s', 0.6, _READ_ONLY)
        self.declare_parameter('learned_paint_every_n', 2, _READ_ONLY)
        self.declare_parameter('learned_paint_threads', 1, _READ_ONLY)
        self.declare_parameter('learned_paint_reuse_max_wz', 0.15)
        self.declare_parameter('learned_paint_motion_compensation', False, _READ_ONLY)
        self.declare_parameter('learned_paint_max_age_s', 0.9, _READ_ONLY)
        self.declare_parameter('learned_paint_max_dxy_m', 0.10, _READ_ONLY)
        self.declare_parameter('learned_paint_max_dyaw_rad', 0.40, _READ_ONLY)
        self.declare_parameter('learned_paint_floor_gate', True, _READ_ONLY)
        self.declare_parameter('camera_lane_mode', 'line', _READ_ONLY)
        self.declare_parameter('lane_half_width_m', 0.0925)
        self.declare_parameter('lane_paint_half_width_m', PAINT_HALF_WIDTH_M, _READ_ONLY)
        self.declare_parameter('camera_roi_bottom_fraction', 1.0)
        self.declare_parameter('camera_between_roi_top_fraction', 0.6)
        self.declare_parameter('camera_between_lane_width_fraction', 0.6, _READ_ONLY)
        self.declare_parameter('camera_ground_source', 'PINKY')
        self.declare_parameter('allow_simulation_ground', False)
        self.declare_parameter('allow_nominal_ground', False, _READ_ONLY)
        self.declare_parameter('nominal_camera_profile_path', '', _READ_ONLY)
        self.declare_parameter('camera_pitch_rad_override', math.nan, _READ_ONLY)
        self.declare_parameter('camera_height_m_override', math.nan, _READ_ONLY)
        self.declare_parameter('camera_pitch_uncertainty_rad_override', math.nan, _READ_ONLY)
        self.declare_parameter('camera_height_uncertainty_m_override', math.nan, _READ_ONLY)
        self.declare_parameter('crosswalk_uncertainty_enabled', False, _READ_ONLY)
        self.declare_parameter('gazebo_camera_height_m', 0.0)
        self.declare_parameter('gazebo_camera_pitch_rad', 0.0)
        self.declare_parameter('gazebo_camera_hfov_rad', 0.0)
        self.declare_parameter('gazebo_camera_max_range_m', 0.6)
        self.declare_parameter('lane_corner_turning', False, _READ_ONLY)
        self.declare_parameter('lane_odom_veto_enabled', False, _READ_ONLY)
        self.declare_parameter('camera_x_offset_m', 0.0)
        self.declare_parameter('debug_overlay', False, _READ_ONLY)
        self.declare_parameter('debug_overlay_max_hz', 5.0)
        self.declare_parameter('debug_lane_graph', '')
        self.declare_parameter('lane_graph_path', '', _READ_ONLY)
        self.declare_parameter('route', Parameter.Type.STRING_ARRAY, _READ_ONLY)
        self.declare_parameter('route_start', Parameter.Type.DOUBLE_ARRAY, _READ_ONLY)

        self._ir_calibration = self._ir_calibration_revision = self._simulation_ground_key = self._simulation_ground = None
        self._nominal_profile_cache = self._ground_error = None
        self._camera_controls_stable = False
        self._paint_half_width_m = paint_half_width(self.get_parameter('lane_paint_half_width_m').value)
        self._odom_pose = self._odom_stamp = self._odom_twist = self._cmd_twist = self._cmd_stamp = None
        cam_x = float(self.get_parameter('camera_x_offset_m').value)
        self._corner_tracker = LaneCornerTracker(camera_x_offset_m=cam_x)
        self._edge_follower = LaneEdgeFollower(
            camera_x_offset_m=cam_x, corner_handoff=bool(self.get_parameter('lane_corner_turning').value))
        self._centre_tracker = LaneBoundaryTracker(camera_x_offset_m=cam_x)
        self._between_keeper = LaneBetweenKeeper(
            default_lane_width_fraction=float(self.get_parameter('camera_between_lane_width_fraction').value))
        self._keep_last_stamp, self._cmd_stale_frames = None, 0
        self._lane_keeper = (OdomVetoLaneKeeper if self.get_parameter('lane_odom_veto_enabled').value else LaneKeeper)(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value),
            corner_turning=bool(self.get_parameter('lane_corner_turning').value), paint_half_width_m=self._paint_half_width_m)
        self._route_context_input, self._paint_worker, self._evidence_modes = RouteContextInput(), self._build_paint_worker(), EvidenceModes()
        configure_drivable_law(self, _READ_ONLY)
        self._wall_ahead, self._lane_guide, self._odom_history, self._route_follower = None, LaneRouteGuideInput(), OdomHistory(), None
        camera_lane_mode = str(self.get_parameter('camera_lane_mode').value)
        if camera_lane_mode in ('route_a', 'route_b', 'route_ab'):
            self._route_follower = self._build_route_follower(camera_lane_mode)
        self._debug_pub = self._debug_last_s = self._debug_graph = None
        if bool(self.get_parameter('debug_overlay').value):
            self._debug_pub = self.create_publisher(CompressedImage, 'line/debug/compressed', 2)
            path = str(self.get_parameter('debug_lane_graph').value)
            if path:
                try:
                    with open(path, encoding='utf-8') as handle:
                        self._debug_graph = yaml.safe_load(handle)
                except (OSError, yaml.YAMLError) as exc:
                    self.get_logger().warning(
                        f'debug_lane_graph {path!r} could not be loaded, map panel will show no route: {exc}')
                    self._debug_graph = None
        self._ir_calibration, self._ir_calibration_revision = build_ir_calibration(self)

        self.observation_pub = self.create_publisher(String, 'line/observation', 10)
        self._keep_debug_pub = self.create_publisher(String, 'line/keep_debug', 10)
        self.create_subscription(UInt16MultiArray, 'ir_sensor/range', self._on_ir, qos_profile_sensor_data)
        self.create_subscription(Image, 'camera/front', self._on_camera, qos_profile_sensor_data)
        controls_qos = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, 'camera/controls', self._on_camera_controls, controls_qos)
        mode = str(self.get_parameter('camera_lane_mode').value)
        if mode in ('lane', 'edge_left', 'centre', 'keep', 'route_a', 'route_b', 'route_ab'):
            self.create_subscription(Odometry, 'odom', self._on_odom, qos_profile_sensor_data)
        if mode == 'keep':
            self.create_subscription(Twist, 'cmd_vel', self._on_cmd_vel, 10)
            if self._drivable_required:
                self.create_subscription(LaserScan, 'scan', self._on_scan, qos_profile_sensor_data)
                subscribe_route_guide(self, String)
            route_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            self.create_subscription(String, 'line/route_context', self._on_route_context, route_qos)
        if self._ir_calibration is None:
            self.get_logger().warning('IR line calibration disabled; IR_LINE will remain fail-closed')

    def _camera_mode_uses_ground(self) -> bool:
        return str(self.get_parameter('camera_lane_mode').value) in (
            'lane', 'edge_left', 'centre', 'keep', 'route_a', 'route_b', 'route_ab')

    def _ground_label(self):
        source = str(self.get_parameter('camera_ground_source').value).strip().upper()
        return 'NOMINAL' if source == 'NOMINAL' else None

    def _ground(self, width: int, height: int):
        source = str(self.get_parameter('camera_ground_source').value)
        if source.strip().upper() == 'NOMINAL':
            key = ('NOMINAL', int(width), int(height))
            if key != self._simulation_ground_key:
                self._simulation_ground = nominal_ground_plane(
                    source=source, allowed=bool(self.get_parameter('allow_nominal_ground').value),
                    width_px=width, height_px=height, profile=self._nominal_profile())
                self._simulation_ground_key = key
            return self._simulation_ground
        plane = dict(source=source,
                     simulation_enabled=bool(self.get_parameter('allow_simulation_ground').value),
                     use_sim_time=bool(self.get_parameter('use_sim_time').value),
                     width_px=int(width), height_px=int(height),
                     **{name: float(self.get_parameter(f'gazebo_camera_{name}').value)
                        for name in ('height_m', 'pitch_rad', 'hfov_rad', 'max_range_m')})
        key = tuple(plane.values())
        if key != self._simulation_ground_key:
            self._simulation_ground = simulation_ground_plane(**plane)
            self._simulation_ground_key = key
        return self._simulation_ground

    def _publish(self, source, observation, *, stamp=None, quality=None, containment=None,
                 route_context_seq=None) -> None:
        if source == 'CAMERA_LINE' and getattr(self._lane_keeper, 'side_conflict_hold', False):
            observation, containment, quality = None, None, quality or dict(valid=False, reason='odom_side_conflict')
        payload = line_observation_payload(
            source, self._stamp() if stamp is None else stamp, observation,
            ir_calibrated=(source == 'IR_LINE' and self._ir_calibration is not None),
            calibration_revision=(self._ir_calibration_revision if source == 'IR_LINE' else None),
            ground=(self._ground_label() if source == 'CAMERA_LINE' and self._camera_mode_uses_ground() else None),
        )
        if quality is not None:
            payload['quality'] = quality
        if containment is not None:
            payload['containment'] = containment
        if route_context_seq is not None and source == 'CAMERA_LINE':
            payload['route_context_seq'] = route_context_seq
        self.observation_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def _build_paint_worker(self):
        source = str(self.get_parameter('paint_source').value)
        if source not in ('threshold', 'denoise', 'learned', 'pink'):
            raise ValueError(f"paint_source must be threshold, denoise, learned or pink, got {source!r}")
        if source != 'learned':
            return None
        from .sensing.perception.learned.paint_worker import TARGETS, LearnedPaintWorker
        target = str(self.get_parameter('learned_paint_target').value)
        if target not in TARGETS:
            raise ValueError(f"learned_paint_target must be one of {TARGETS}, got {target!r}")
        from perception_runtime.perception.learned.runner import LaneSegModel, ModelSlot, add_learned_site
        add_learned_site()
        pointer = str(self.get_parameter('learned_lane_pointer').value)
        if not pointer:
            self.get_logger().warning('paint_source learned without learned_lane_pointer: denoise only')
        every_n = int(self.get_parameter('learned_paint_every_n').value)
        threads = int(self.get_parameter('learned_paint_threads').value)
        if every_n < 1 or threads < 1:
            raise ValueError('learned_paint_every_n and learned_paint_threads must be >= 1')
        floor_gate = bool(self.get_parameter('learned_paint_floor_gate').value)
        slot = ModelSlot(pointer, opener=lambda folder: LaneSegModel.open(
            folder, threads=threads, allow_spinning=False, floor_gate=floor_gate,
            paint_target=target)) if pointer else None
        return LearnedPaintWorker(
            slot, stale_s=float(self.get_parameter('learned_paint_stale_s').value),
            warn=self.get_logger().warning, target=target)

    def _drop_learned_paint(self):
        if self._paint_worker is not None:
            self._paint_worker.reset()
        self._evidence_modes.reset()

    def _paint_for(self, frame, ground, stamp=None):
        source = str(self.get_parameter('paint_source').value)
        if source == 'pink':
            return floor_pink_mask(frame, ground.horizon_row), 'pink'
        if source == 'threshold' or ground is None:
            self._drop_learned_paint()
            self._evidence_modes.choose_lane(armed=False, model_fresh=False, learned_ok=False, denoise_ok=False)
            return None, 'threshold'
        if source == 'learned' and self._paint_worker is not None:
            every_n = int(self.get_parameter('learned_paint_every_n').value)
            reuse_n = every_n
            wz = pose_if_fresh(self._odom_twist and self._odom_twist[1], self._odom_stamp, stamp)
            if wz is None or abs(wz) > float(self.get_parameter('learned_paint_reuse_max_wz').value):
                reuse_n = 1
            compensate = bool(self.get_parameter('learned_paint_motion_compensation').value)
            motion = self._paint_motion(ground) if compensate and wz is not None else None
            mask = self._paint_worker.mask_for(
                frame, every_n if motion is not None else reuse_n, stamp,
                clean=lambda m: clean_learned_mask(m, ground.horizon_row),
                motion=motion, max_age_s=float(self.get_parameter('learned_paint_max_age_s').value),
                reuse_n=reuse_n, clean_drivable=lambda way: clean_learned_mask(boundary_paint(
                    way > 0, lateral_px_per_m(np.arange(way.shape[0]), focal_px=ground.focal_px,
                                              principal_y=ground.principal_y, pitch_rad=ground.pitch_rad,
                                              height_m=ground.height_m),
                    self._paint_half_width_m), ground.horizon_row))
            reuse = self._paint_worker.reuse
            if compensate and motion is None and reuse and reuse['paint_warp_skipped'] == 'off':
                reuse['paint_warp_skipped'] = 'no_odom'
            chosen = self._evidence_modes.choose_lane(
                armed=True, model_fresh=mask is not None, learned_ok=mask is not None, denoise_ok=True)
            if chosen == 'learned' and mask is not None:
                return mask, 'learned_drivable' if self._paint_worker.used_paint_kind == 'drivable' else 'learned'
            return denoise_white_mask(frame, ground.horizon_row), 'denoise_fallback'
        self._evidence_modes.choose_lane(armed=False, model_fresh=False, learned_ok=False, denoise_ok=True, unarmed='denoise')
        return denoise_white_mask(frame, ground.horizon_row), ('denoise' if source == 'denoise' else 'denoise_fallback')

    def _on_camera(self, msg: Image) -> None:
        observation = frame = mode = ground = quality = route_context_seq = None
        if bool(self.get_parameter('require_camera_controls_stable').value) and not self._camera_controls_stable:
            self._publish('CAMERA_LINE', None, stamp=float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9)
            self._keep_last_stamp = None
            self._drop_learned_paint()
            return
        try:
            frame = image_msg_to_frame(msg)
            reason = visibility_reason(frame)
            if reason != 'usable':
                self._lane_keeper.reset()
                self._between_keeper.reset()
                self._keep_last_stamp = None
                self._drop_learned_paint()
                source_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                self._publish('CAMERA_LINE', None, stamp=source_stamp, quality=dict(valid=False, reason=reason))
                self._publish_debug(msg, frame, None)
                return
            mode = str(self.get_parameter('camera_lane_mode').value)
            if mode != 'keep':
                self._drop_learned_paint()
            if mode == 'line':
                observation = detect_lane_error(
                    frame, bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    roi_top_fraction=float(self.get_parameter('camera_roi_top_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value),
                    min_pixels=int(self.get_parameter('camera_min_pixels').value))
            elif mode == 'between':
                observation = self._between_keeper.update(
                    frame, bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    roi_top_fraction=float(self.get_parameter('camera_between_roi_top_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value))
            elif mode == 'keep':
                refresh_drivable_law(self)
                image_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                route_context = self._route_context_input.for_frame(image_stamp)
                route_context_seq = route_context.seq if route_context is not None else None
                bend_rules = bend_expected(route_context)
                cmd = pose_if_fresh(self._cmd_twist, self._cmd_stamp, image_stamp)
                self._cmd_stale_frames = 0 if cmd is not None or self._cmd_twist is None else self._cmd_stale_frames + 1
                if self._cmd_stale_frames >= KEEP_CMD_STALE_WARN_FRAMES:
                    self.get_logger().warning('cmd_vel stale vs camera stamps; spin reset off (use_sim_time?)', once=True)
                if (self._keep_last_stamp is None
                        or not 0.0 <= image_stamp - self._keep_last_stamp <= KEEP_MAX_FRAME_GAP_S
                        or _spinning_in_place(cmd)):
                    self._lane_keeper.reset()
                    if self._paint_worker is not None and self._drivable_steer is None:
                        self._drop_learned_paint()
                self._keep_last_stamp = image_stamp
                ground = self._ground(frame.shape[1], frame.shape[0])
                paint, paint_used = self._paint_for(frame, ground, image_stamp)
                observation = self._lane_keeper.update(
                    frame, ground, paint_mask=paint,
                    crosswalk_mask=(self._paint_worker.used_crosswalk if paint_used == 'learned_drivable' else None),
                    lane_half_width_m=float(self.get_parameter('lane_half_width_m').value),
                    pose=pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                    bend_expected=bend_rules)
                if self._drivable_required and self._drivable_steer is None:
                    observation = None
                    self._lane_keeper.last.update(strategy='none', reason='core_steering_law_unavailable')
                elif self._drivable_steer is not None:
                    try:
                        step, decided = keep_step(
                            self._drivable_steer, self._paint_worker, self._lane_keeper.last, ground,
                            self._lane_keeper._x_offset, float(self.get_parameter('lane_half_width_m').value),
                            self._odom_history.pose_at, image_stamp, self._wall_ahead,
                            self._lane_guide.for_frame(image_stamp), guide_generation=self._lane_guide.generation)
                    except Exception as exc:  # noqa: BLE001
                        self.get_logger().error(f'drivable steer failed: {exc!r}', throttle_duration_sec=5.0)
                        self._drivable_steer.reset()
                        step, decided = None, True
                    observation = None if step is None else LaneObservation(error=step[0], confidence=step[1])
                    paint_used = 'learned_drivable' if decided else paint_used
                bundle = keep_debug_payload(
                    self._lane_keeper.last, ground, self._lane_keeper._x_offset,
                    paint_source_used=paint_used,
                    paint_source_requested=str(self.get_parameter('paint_source').value),
                    paint_model_revision=(self._paint_worker.used_model_revision
                                          if paint_used in ('learned', 'learned_drivable') and self._paint_worker is not None else None),
                    paint_target_requested=(self._paint_worker.target if self._paint_worker is not None else None),
                    paint_drivable=(self._paint_worker.used_drivable if self._paint_worker is not None else None),
                    paint_floor_gate=(bool(self.get_parameter('learned_paint_floor_gate').value) if self._paint_worker is not None else None),
                    paint_last_error=(self._paint_worker.last_error if self._paint_worker is not None else None),
                    **((self._paint_worker.reuse or {}) if self._paint_worker is not None else {}),
                    image_size=[frame.shape[1], frame.shape[0]],
                    camera_geometry_source=str(self.get_parameter('camera_ground_source').value).upper(),
                    evidence_mode=self._evidence_modes.lane,
                    evidence_rows=self._evidence_modes.rows(
                        crosswalk=self._lane_keeper.last.get('crosswalk') is not None, stop_line=False, obstacle=False),
                    corner_turning=bool(self.get_parameter('lane_corner_turning').value),
                    ground=self._ground_label(), stamp=image_stamp, route_context_v=1,
                    route_context_seq=route_context.seq if route_context is not None else None,
                    route_context_effect={'bend_rules': True} if bend_rules else None)
                self._keep_debug_pub.publish(String(data=json.dumps(bundle, default=float)))
            elif mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab'):
                if (mode in ('route_a', 'route_b', 'route_ab') and self._route_follower is not None
                        and not simulation_ground_allowed(
                            source=self.get_parameter('camera_ground_source').value,
                            simulation_enabled=self.get_parameter('allow_simulation_ground').value,
                            use_sim_time=self.get_parameter('use_sim_time').value)):
                    self._route_follower = None
                    self.get_logger().warning(f'{mode} simulation context changed; route follower revoked', once=True)
                ground = self._ground(frame.shape[1], frame.shape[0])
                lane_kwargs = dict(
                    bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    lane_half_width_m=float(self.get_parameter('lane_half_width_m').value),
                    roi_top_fraction=float(self.get_parameter('camera_roi_top_fraction').value),
                    roi_bottom_fraction=float(self.get_parameter('camera_roi_bottom_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value))
                if mode == 'centre':
                    image_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                    observation = self._centre_tracker.update(
                        image_stamp, pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                elif mode == 'edge_left':
                    image_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                    observation = self._edge_follower.update(
                        image_stamp, pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                elif mode in ('route_a', 'route_b', 'route_ab'):
                    if self._route_follower is not None:
                        image_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                        observation = self._route_follower.update(
                            image_stamp, pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                            frame, ground, **lane_kwargs)
                        if mode == 'route_a' and self._route_follower.last.get('reason') == 'washed':
                            observation = None
                            quality = dict(valid=False, reason='overexposed')
                elif bool(self.get_parameter('lane_corner_turning').value):
                    image_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                    observation = self._corner_tracker.update(
                        image_stamp, pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                else:
                    observation = detect_lane_centre(frame, ground, **lane_kwargs)
            else:
                raise ValueError(f'unsupported camera_lane_mode {mode!r}')
        except ValueError as exc:
            observation = None
            self.get_logger().warning(f'invalid camera line frame: {exc}')
        source_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        containment = None
        if mode == 'keep' and observation is not None:
            containment = containment_payload(
                self._lane_keeper.last, ground, stamp=source_stamp,
                source=str(self.get_parameter('camera_ground_source').value).upper(),
                camera_x=self._lane_keeper._x_offset, geometry_bounds=self._ground_error,
                paint_half_width_m=self._paint_half_width_m,
                crosswalk_uncertainty=bool(self.get_parameter('crosswalk_uncertainty_enabled').value))
        self._publish('CAMERA_LINE', observation, stamp=source_stamp,
                      quality=quality, containment=containment,
                      route_context_seq=route_context_seq)
        self._publish_debug(msg, frame, observation)

    def _publish_debug(self, msg, frame, observation) -> None:
        if self._debug_pub is None or frame is None: return
        stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        if not next_publish_due(self._debug_last_s, stamp, float(self.get_parameter('debug_overlay_max_hz').value)): return
        self._debug_last_s = stamp
        mode = str(self.get_parameter('camera_lane_mode').value)
        follower = {
            'centre': self._centre_tracker, 'edge_left': self._edge_follower,
            'route_a': self._route_follower, 'route_b': self._route_follower,
            'route_ab': self._route_follower,
        }.get(mode)
        if follower is None: return
        try:
            image = render_debug(
                frame, follower, observation, mode=mode,
                pose=pose_if_fresh(self._odom_pose, self._odom_stamp, stamp),
                graph=self._debug_graph,
                bright_threshold=int(self.get_parameter('camera_bright_threshold').value))
            if (out := encode_debug_overlay_msg(msg.header, image)) is not None:
                self._debug_pub.publish(out)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f'debug overlay render/publish failed: {exc}', throttle_duration_sec=5.0)

    def _on_odom(self, msg: Odometry) -> None:
        pose, q = msg.pose.pose, msg.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        self._odom_pose = (float(pose.position.x), float(pose.position.y), yaw)
        self._odom_twist = (float(msg.twist.twist.linear.x), float(msg.twist.twist.angular.z))
        self._odom_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        self._odom_history.add(self._odom_stamp, *self._odom_pose)

    def _on_cmd_vel(self, msg: Twist) -> None:
        self._cmd_twist, self._cmd_stamp = (msg.linear.x, msg.angular.z), self.get_clock().now().nanoseconds * 1e-9


def main():
    rclpy.init()
    node = LineObserverNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
