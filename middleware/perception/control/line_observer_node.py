#!/usr/bin/env python3
"""Publish normalized white-line evidence from IR reflectance or camera frames.

This node owns no motion output. CORE chooses exactly one source and remains
the sole final ``cmd_vel`` publisher (D-143).
"""

import json
import math
import os

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String, UInt16MultiArray

from . import executor_choice
from .route_context_input import RouteContextInput, bend_expected
from .calibrated_values import calibrated
from .sensing.perception.camera_ground import (
    nominal_ground_plane, simulation_ground_allowed, simulation_ground_plane,
)
from .sensing.perception.image_frame import image_msg_to_frame
from .sensing.perception.camera_visibility import visibility_reason
from .sensing.perception.lane import (
    IRLineCalibration,
    LaneBetweenKeeper,
    LaneCornerTracker,
    detect_ir_line,
    detect_lane_centre,
    detect_lane_error,
    line_observation_payload,
)
from .sensing.perception.lane_bev import LaneEdgeFollower, pose_if_fresh
from .sensing.perception.lane_boundaries import LaneBoundaryTracker
from .sensing.perception.lane_keep import LaneKeeper, clean_learned_mask, denoise_white_mask
from .sensing.perception.lane_keep_lines import HORIZON_MARGIN_PX, drop_small_components
from .sensing.perception.learned.drivable_paint import boundary_paint, lateral_px_per_m
from .sensing.perception.learned.paint_motion import OdomHistory, mask_homography, warp_mask
from .sensing.perception.lane_debug import keep_debug_payload, next_publish_due, render_debug
from .sensing.perception.lane_containment import PAINT_HALF_WIDTH_M, containment_payload, geometry_error, paint_half_width
from .sensing.perception.paint_localizer import PaintMap
from .sensing.perception.route_camera import RouteCameraFollower
from .sensing.perception.route_hybrid import RouteHybridFollower
from .sensing.perception.route_map import RouteMapFollower

#: Fixed at startup: the edge follower and odom subscription are built from these once (a change runs the wrong pipeline).
_READ_ONLY = ParameterDescriptor(read_only=True)
#: 'keep' mode: a gap between camera frames longer than this resets the keeper.
KEEP_MAX_FRAME_GAP_S = 0.5


COMMANDED_PIVOT_LINEAR_MPS = 1e-3   # a pivot commands v exactly 0; slow keep steering commands ~0.01 m/s
KEEP_CMD_STALE_WARN_FRAMES = 30     # 'keep': frames in a row with a stale received command before one warning


#: A spin in place, judged on CORE's commanded (v, w): |w| over half D-495's 0.3 rad/s turn floor, |v| near 0.
#: Not on odom: a slow keep corner (cmd v 0.0188) reads vx ~0.001 (D-507 r4b).
def _spinning_in_place(twist):
    return twist is not None and abs(twist[1]) > 0.15 and abs(twist[0]) < COMMANDED_PIVOT_LINEAR_MPS


class LineObserverNode(Node):
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
        # 'line' follows one bright line; 'lane' keeps the centre between two boundary lines; 'edge_left'
        # holds the lane's left boundary a half-width off in bird's-eye view (bends, arcs). Both lane
        # modes need a metric ground plane, edge_left also odometry (fail-closed without).
        # 'centre' follows the centre line between both boundaries (fallback ladder).
        # 'between' keeps the midpoint of the two boundary lines in image space (no ground plane, no odometry).
        # 'keep' keeps the lane middle from ground-plane boundary lines found per frame: the real-robot
        # lane keeper (D-364 §2), on camera_ground_source NOMINAL + allow_nominal_ground, or GAZEBO.
        # 'route_a'/'route_b' are the junction prototypes: route-driven
        # manoeuvres over the centre-line tracker (A) and planned-route
        # pursuit from a paint-localised pose (B). 'route_ab' is their
        # hybrid: A's manoeuvres placed by B's paint-localised pose. All
        # need lane_graph_path/route/route_start; fail closed without them.
        # D-408: keep-mode paint source: threshold (default) | denoise | learned (+ denoise fallback).
        self.declare_parameter('paint_source', 'threshold', _READ_ONLY)
        self.declare_parameter('learned_lane_pointer', '', _READ_ONLY)
        # D-NNN: what of the learned model's output becomes paint: its lane_marking classes (default), or
        # the boundaries of the drivable way through its drivable class (lane_marking when it has none).
        self.declare_parameter('learned_paint_target', 'lane_marking', _READ_ONLY)
        self.declare_parameter('learned_paint_stale_s', 0.6, _READ_ONLY)
        # D-408 CPU: infer on every Nth keep frame (the mask is reused in between), on 1 thread.
        self.declare_parameter('learned_paint_every_n', 2, _READ_ONLY)
        self.declare_parameter('learned_paint_threads', 1, _READ_ONLY)
        # Turning moves the image between frames: above this |odom wz| (or with no fresh odom) the
        # mask is not reused (cadence 1: every frame infers, a late mask falls back to denoise).
        self.declare_parameter('learned_paint_reuse_max_wz', 0.15)
        # D-570: move an older mask to this frame by the odometry between the two frame stamps
        # (ground-plane homography); within these bounds the turn-rate rule above does not apply.
        self.declare_parameter('learned_paint_motion_compensation', False, _READ_ONLY)
        self.declare_parameter('learned_paint_max_age_s', 0.9, _READ_ONLY)
        self.declare_parameter('learned_paint_max_dxy_m', 0.10, _READ_ONLY)
        self.declare_parameter('learned_paint_max_dyaw_rad', 0.40, _READ_ONLY)
        self.declare_parameter('camera_lane_mode', 'line', _READ_ONLY)
        self.declare_parameter('lane_half_width_m', 0.0925)
        self.declare_parameter('lane_paint_half_width_m', PAINT_HALF_WIDTH_M, _READ_ONLY)
        self.declare_parameter('camera_roi_bottom_fraction', 1.0)
        # 'between' only: bottom band start (keeps white walls out), lane width as a frame fraction until both are seen.
        self.declare_parameter('camera_between_roi_top_fraction', 0.6)
        self.declare_parameter('camera_between_lane_width_fraction', 0.6, _READ_ONLY)
        self.declare_parameter('camera_ground_source', 'PINKY')
        self.declare_parameter('allow_simulation_ground', False)
        # D-364 §3: estimated floor geometry for the real camera. Two opt-ins, and
        # the evidence is labelled NOMINAL so CORE accepts it only under a driver hold.
        self.declare_parameter('allow_nominal_ground', False, _READ_ONLY)
        self.declare_parameter('nominal_camera_profile_path', '', _READ_ONLY)
        # D-397 operator layer: a finite value wins over the URDF-nominal file and an
        # accepted camera_profile record; NaN (default) = no override.
        self.declare_parameter('camera_pitch_rad_override', math.nan, _READ_ONLY)
        self.declare_parameter('camera_height_m_override', math.nan, _READ_ONLY)
        self.declare_parameter('gazebo_camera_height_m', 0.0)
        self.declare_parameter('gazebo_camera_pitch_rad', 0.0)
        self.declare_parameter('gazebo_camera_hfov_rad', 0.0)
        self.declare_parameter('gazebo_camera_max_range_m', 0.6)
        # Lane mode only: odometry-bounded 90 deg corner turning; off by default, never leaves FOLLOW without odometry.
        self.declare_parameter('lane_corner_turning', False, _READ_ONLY)
        self.declare_parameter('camera_x_offset_m', 0.0)
        self.declare_parameter('debug_overlay', False, _READ_ONLY)
        self.declare_parameter('debug_overlay_max_hz', 5.0)
        self.declare_parameter('debug_lane_graph', '')
        # route_a/route_b/route_ab only. route and route_start are declared by type, not value: an
        # empty Python list default cannot be typed, and the config file's own empty-list override
        # (line_follow.yaml) needs a declared element type (string / double) to resolve against.
        self.declare_parameter('lane_graph_path', '', _READ_ONLY)
        self.declare_parameter('route', Parameter.Type.STRING_ARRAY, _READ_ONLY)
        self.declare_parameter('route_start', Parameter.Type.DOUBLE_ARRAY, _READ_ONLY)

        self._ir_calibration = self._ir_calibration_revision = None
        self._camera_controls_stable = False
        self._simulation_ground_key = self._simulation_ground = None
        self._nominal_profile_cache = None
        self._ground_error = None
        self._paint_half_width_m = paint_half_width(self.get_parameter('lane_paint_half_width_m').value)
        self._odom_pose = self._odom_stamp = self._odom_twist = self._cmd_twist = self._cmd_stamp = None
        self._corner_tracker = LaneCornerTracker(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value))
        self._edge_follower = LaneEdgeFollower(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value),
            corner_handoff=bool(self.get_parameter('lane_corner_turning').value))
        self._centre_tracker = LaneBoundaryTracker(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value))
        self._between_keeper = LaneBetweenKeeper(
            default_lane_width_fraction=float(
                self.get_parameter('camera_between_lane_width_fraction').value))
        self._keep_last_stamp, self._cmd_stale_frames = None, 0
        self._lane_keeper = LaneKeeper(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value),
            corner_turning=bool(self.get_parameter('lane_corner_turning').value), paint_half_width_m=self._paint_half_width_m)
        self._route_context_input = RouteContextInput()
        self._paint_worker = self._build_paint_worker()
        self._odom_history = OdomHistory()
        self._route_follower = None
        camera_lane_mode = str(self.get_parameter('camera_lane_mode').value)
        if camera_lane_mode in ('route_a', 'route_b', 'route_ab'):
            self._route_follower = self._build_route_follower(camera_lane_mode)
        self._debug_pub = self._debug_last_s = self._debug_graph = None
        if bool(self.get_parameter('debug_overlay').value):
            self._debug_pub = self.create_publisher(
                CompressedImage, 'line/debug/compressed', 2)
            path = str(self.get_parameter('debug_lane_graph').value)
            if path:
                # A missing or malformed graph must never fail startup
                # (D-143: this node still owes CORE line/observation); the
                # map panel just goes without a route overlay.
                try:
                    with open(path, encoding='utf-8') as handle:
                        self._debug_graph = yaml.safe_load(handle)
                except (OSError, yaml.YAMLError) as exc:
                    self.get_logger().warning(
                        f'debug_lane_graph {path!r} could not be loaded, '
                        f'map panel will show no route: {exc}')
                    self._debug_graph = None
        if bool(self.get_parameter('ir_calibration_enabled').value):
            self._ir_calibration = IRLineCalibration(
                black=tuple(self.get_parameter('ir_black').value),
                white=tuple(self.get_parameter('ir_white').value),
                min_span=float(self.get_parameter('ir_min_span').value),
            )
            self._ir_calibration_revision = self._ir_calibration.revision

        self.observation_pub = self.create_publisher(String, 'line/observation', 10)
        # D-364: the keep lane keeper's decision bundle (strategy, boundaries,
        # target) per frame, for the pilot overlay and exact closed-loop replay.
        # Observation only; CORE does not read it.
        self._keep_debug_pub = self.create_publisher(String, 'line/keep_debug', 10)
        self.create_subscription(
            UInt16MultiArray, 'ir_sensor/range', self._on_ir, qos_profile_sensor_data)
        self.create_subscription(
            Image, 'camera/front', self._on_camera, qos_profile_sensor_data)
        controls_qos = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(
            String, 'camera/controls', self._on_camera_controls, controls_qos)
        mode = str(self.get_parameter('camera_lane_mode').value)
        if mode in ('lane', 'edge_left', 'centre', 'keep', 'route_a', 'route_b', 'route_ab'):
            self.create_subscription(
                Odometry, 'odom', self._on_odom, qos_profile_sensor_data)
        if mode == 'keep':   # read only: CORE stays the sole final cmd_vel publisher (D-18, D-143)
            self.create_subscription(Twist, 'cmd_vel', self._on_cmd_vel, 10)
            route_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            self.create_subscription(
                String, 'line/route_context', self._on_route_context, route_qos)
        if self._ir_calibration is None:
            self.get_logger().warning(
                'IR line calibration disabled; IR_LINE will remain fail-closed')

    def _build_route_follower(self, mode: str):
        """route_a/route_b/route_ab only. Missing or invalid lane_graph_path, route or
        route_start (or a graph/route that fails to build, e.g. a
        disconnected pair or a one-way ring arc walked backwards) fails
        closed: a warning logged once here at startup, no follower built,
        and CAMERA_LINE keeps publishing None (visible:false) every frame
        rather than going silent (D-143: this node still owes CORE
        evidence)."""
        # A static route_start anchors the first odometry pose without an
        # independent map fix. Keep these junction prototypes in simulation
        # until an active map and fresh localized start can authorize them.
        if not simulation_ground_allowed(
                source=self.get_parameter('camera_ground_source').value,
                simulation_enabled=self.get_parameter('allow_simulation_ground').value,
                use_sim_time=self.get_parameter('use_sim_time').value):
            self.get_logger().warning(
                f'{mode} prototype route modes require Gazebo simulation ground and clock; '
                'no follower built, CAMERA_LINE will publish no observation')
            return None
        graph_path = str(self.get_parameter('lane_graph_path').value)
        route = [str(key) for key in self.get_parameter('route').value]
        route_start = [float(v) for v in self.get_parameter('route_start').value]
        if not graph_path or not route or len(route_start) != 3:
            self.get_logger().warning(
                f'{mode} route modes need lane_graph_path, route and route_start; '
                'no follower built, CAMERA_LINE will publish no observation')
            return None
        try:
            with open(graph_path, encoding='utf-8') as handle:
                graph = yaml.safe_load(handle)
            x_offset = float(self.get_parameter('camera_x_offset_m').value)
            if mode == 'route_a':
                return RouteCameraFollower(
                    graph, route, start_pose=tuple(route_start), camera_x_offset_m=x_offset)
            paint_map = PaintMap.from_bundle(os.path.dirname(graph_path))
            if mode == 'route_ab':
                return RouteHybridFollower(
                    graph, route, start_pose=tuple(route_start),
                    camera_x_offset_m=x_offset, paint_map=paint_map)
            return RouteMapFollower(
                graph, route, start_pose=tuple(route_start), camera_x_offset_m=x_offset,
                paint_map=paint_map)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            self.get_logger().warning(
                f'{mode} route modes need lane_graph_path, route and route_start '
                f'to build a valid follower ({exc}); no follower built, '
                'CAMERA_LINE will publish no observation')
            return None

    def _nominal_profile(self):
        if self._nominal_profile_cache is None:
            path = str(self.get_parameter('nominal_camera_profile_path').value)
            try:
                with open(path, encoding='utf-8') as handle:
                    self._nominal_profile_cache = yaml.safe_load(handle) or {}
            except (OSError, yaml.YAMLError) as exc:
                self.get_logger().warning(
                    f'nominal camera profile unreadable ({exc}); no NOMINAL ground',
                    throttle_duration_sec=5.0)
                self._nominal_profile_cache = {}
            # An operator-accepted camera_profile record wins over the file (D-47 addendum).
            override = {key: float(self.get_parameter(f'camera_{key}_override').value)
                        for key in ('pitch_rad', 'height_m')}
            override = {k: v for k, v in override.items() if math.isfinite(v)}
            self._nominal_profile_cache, source, intervals = calibrated(
                'camera_profile', self._nominal_profile_cache, static_source=path or 'no profile file',
                override=override, with_intervals=True)
            # D-468: the stated error of this geometry (record bands or nominal bounds), else None.
            self._ground_error = geometry_error(self._nominal_profile_cache, intervals, overridden=override)
            self.get_logger().info(f'camera profile from {source}; geometry error {self._ground_error}')
        return self._nominal_profile_cache

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
                    source=source,
                    allowed=bool(self.get_parameter('allow_nominal_ground').value),
                    width_px=width, height_px=height,
                    profile=self._nominal_profile())
                self._simulation_ground_key = key
            return self._simulation_ground
        simulation_enabled = bool(
            self.get_parameter('allow_simulation_ground').value)
        use_sim_time = bool(self.get_parameter('use_sim_time').value)
        height_m = float(self.get_parameter('gazebo_camera_height_m').value)
        pitch_rad = float(self.get_parameter('gazebo_camera_pitch_rad').value)
        hfov_rad = float(self.get_parameter('gazebo_camera_hfov_rad').value)
        max_range_m = float(self.get_parameter(
            'gazebo_camera_max_range_m').value)
        key = (source, simulation_enabled, use_sim_time, int(width),
               int(height), height_m, pitch_rad, hfov_rad, max_range_m)
        if key != self._simulation_ground_key:
            self._simulation_ground = simulation_ground_plane(
                source=source,
                simulation_enabled=simulation_enabled,
                use_sim_time=use_sim_time,
                width_px=width,
                height_px=height,
                height_m=height_m,
                pitch_rad=pitch_rad,
                hfov_rad=hfov_rad,
                max_range_m=max_range_m,
            )
            self._simulation_ground_key = key
        return self._simulation_ground

    def _stamp(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _publish(self, source, observation, *, stamp=None, quality=None, containment=None,
                 route_context_seq=None) -> None:
        payload = line_observation_payload(
            source, self._stamp() if stamp is None else stamp, observation,
            ir_calibrated=(source == 'IR_LINE' and self._ir_calibration is not None),
            calibration_revision=(self._ir_calibration_revision
                                  if source == 'IR_LINE' else None),
            ground=(self._ground_label()
                    if source == 'CAMERA_LINE' and self._camera_mode_uses_ground() else None),
        )
        if quality is not None:
            payload['quality'] = quality
        if containment is not None:
            payload['containment'] = containment
        if route_context_seq is not None and source == 'CAMERA_LINE':
            payload['route_context_seq'] = route_context_seq
        self.observation_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def _on_route_context(self, msg: String) -> None:
        self._route_context_input.receive(msg.data)

    def _on_ir(self, msg: UInt16MultiArray) -> None:
        observation = None
        if self._ir_calibration is not None:
            try:
                observation = detect_ir_line(
                    list(msg.data), self._ir_calibration,
                    min_white=float(self.get_parameter('ir_min_white').value),
                    min_contrast=float(self.get_parameter('ir_min_contrast').value),
                )
            except ValueError as exc:
                self.get_logger().warning(f'invalid IR line sample: {exc}')
        self._publish('IR_LINE', observation)

    def destroy_node(self):
        if self._paint_worker is not None:
            self._paint_worker.close()
        return super().destroy_node()

    def _build_paint_worker(self):
        """D-408: the learned paint source runs the lane model off the camera thread."""
        source = str(self.get_parameter('paint_source').value)
        if source not in ('threshold', 'denoise', 'learned'):
            raise ValueError(f"paint_source must be threshold, denoise or learned, got {source!r}")
        if source != 'learned':
            return None
        from .sensing.perception.learned.paint_worker import TARGETS, LearnedPaintWorker
        target = str(self.get_parameter('learned_paint_target').value)
        if target not in TARGETS:
            raise ValueError(f"learned_paint_target must be one of {TARGETS}, got {target!r}")
        from .sensing.perception.learned.runner import LaneSegModel, ModelSlot, add_learned_site
        add_learned_site()
        pointer = str(self.get_parameter('learned_lane_pointer').value)
        if not pointer:
            self.get_logger().warning('paint_source learned without learned_lane_pointer: denoise only')
        every_n = int(self.get_parameter('learned_paint_every_n').value)
        threads = int(self.get_parameter('learned_paint_threads').value)
        if every_n < 1 or threads < 1:
            raise ValueError('learned_paint_every_n and learned_paint_threads must be >= 1')
        slot = ModelSlot(pointer, opener=lambda folder: LaneSegModel.open(
            folder, threads=threads, allow_spinning=False)) if pointer else None
        return LearnedPaintWorker(slot,
                                  stale_s=float(self.get_parameter('learned_paint_stale_s').value),
                                  warn=self.get_logger().warning, target=target)

    def _paint_for(self, frame, ground, stamp=None):
        """(paint mask or None, source actually used) for one keep frame (D-408)."""
        source = str(self.get_parameter('paint_source').value)
        if source == 'threshold' or ground is None:
            if self._paint_worker is not None:
                self._paint_worker.reset()
            return None, 'threshold'
        if source == 'learned' and self._paint_worker is not None:
            every_n = int(self.get_parameter('learned_paint_every_n').value)
            reuse_n = every_n
            wz = pose_if_fresh(self._odom_twist and self._odom_twist[1], self._odom_stamp, stamp)
            if wz is None or abs(wz) > float(self.get_parameter('learned_paint_reuse_max_wz').value):
                reuse_n = 1
            # D-570: with fresh odometry the warped path replaces the turn-rate rule; without it, today's rule.
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
            if mask is not None:
                return mask, 'learned_drivable' if self._paint_worker.used_paint_kind == 'drivable' else 'learned'
        return denoise_white_mask(frame, ground.horizon_row), (
            'denoise' if source == 'denoise' else 'denoise_fallback')

    def _paint_motion(self, ground):
        """motion(mask, src_stamp, dst_stamp) for the paint worker (D-570): the mask warped by the
        odometry between the two stamps, or why not (no_odom / motion_bound)."""
        cut = max(0, int(math.ceil(ground.horizon_row)) + HORIZON_MARGIN_PX)

        def motion(mask, src_stamp, dst_stamp):
            src, dst = self._odom_history.pose_at(src_stamp), self._odom_history.pose_at(dst_stamp)
            if src is None or dst is None:
                return 'no_odom'
            moved = mask_homography(
                ground, self._lane_keeper._x_offset, src, dst, mask.shape, cut,
                max_dxy_m=float(self.get_parameter('learned_paint_max_dxy_m').value),
                max_dyaw_rad=float(self.get_parameter('learned_paint_max_dyaw_rad').value))
            if isinstance(moved, str):
                return moved
            homography, dxy, dyaw = moved
            # resampling can split tape into specks: drop them like clean_learned_mask does
            return drop_small_components(warp_mask(mask, homography, cut)), dxy, dyaw
        return motion

    def _on_camera(self, msg: Image) -> None:
        observation = None
        frame = None
        mode = None
        ground = None
        quality = None
        route_context_seq = None
        if (bool(self.get_parameter(
                'require_camera_controls_stable').value)
                and not self._camera_controls_stable):
            self._publish('CAMERA_LINE', None, stamp=(
                float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9))
            self._keep_last_stamp = None
            if self._paint_worker is not None:
                self._paint_worker.reset()
            return
        try:
            frame = image_msg_to_frame(msg)
            reason = visibility_reason(frame)
            if reason != 'usable':
                self._lane_keeper.reset()
                self._between_keeper.reset()
                self._keep_last_stamp = None
                if self._paint_worker is not None:
                    self._paint_worker.reset()
                source_stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
                self._publish('CAMERA_LINE', None, stamp=source_stamp,
                              quality=dict(valid=False, reason=reason))
                self._publish_debug(msg, frame, None)
                return
            mode = str(self.get_parameter('camera_lane_mode').value)
            if mode != 'keep' and self._paint_worker is not None:
                self._paint_worker.reset()
            if mode == 'line':
                observation = detect_lane_error(
                    frame,
                    bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    roi_top_fraction=float(self.get_parameter('camera_roi_top_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value),
                    min_pixels=int(self.get_parameter('camera_min_pixels').value),
                )
            elif mode == 'between':
                observation = self._between_keeper.update(
                    frame,
                    bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    roi_top_fraction=float(
                        self.get_parameter('camera_between_roi_top_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value),
                )
            elif mode == 'keep':
                # A camera gap (or the first keep frame of this node) starts the keeper afresh: sides and steering
                # from before the gap may belong to another place. So does a commanded spin in place (D-507: its
                # swept view latched the flip hold).
                image_stamp = (float(msg.header.stamp.sec)
                               + float(msg.header.stamp.nanosec) * 1e-9)
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
                    if self._paint_worker is not None:
                        self._paint_worker.reset()
                self._keep_last_stamp = image_stamp
                ground = self._ground(frame.shape[1], frame.shape[0])
                paint, paint_used = self._paint_for(frame, ground, image_stamp)
                observation = self._lane_keeper.update(
                    frame, ground, paint_mask=paint,
                    lane_half_width_m=float(self.get_parameter('lane_half_width_m').value),
                    bend_expected=bend_rules)
                bundle = keep_debug_payload(
                              self._lane_keeper.last, ground, self._lane_keeper._x_offset,
                              paint_source_used=paint_used,
                              paint_source_requested=str(self.get_parameter('paint_source').value),
                              paint_model_revision=(self._paint_worker.used_model_revision
                                                    if paint_used in ('learned', 'learned_drivable')
                                                    and self._paint_worker is not None else None),
                              paint_target_requested=(self._paint_worker.target
                                                      if self._paint_worker is not None else None),
                              paint_drivable=(self._paint_worker.used_drivable
                                              if self._paint_worker is not None else None),
                              **((self._paint_worker.reuse or {}) if self._paint_worker is not None else {}),
                              image_size=[frame.shape[1], frame.shape[0]],
                              camera_geometry_source=str(self.get_parameter('camera_ground_source').value).upper(),
                              corner_turning=bool(self.get_parameter('lane_corner_turning').value),
                              ground=self._ground_label(), stamp=image_stamp,
                              route_context_v=1,
                              route_context_seq=route_context.seq if route_context is not None else None,
                              route_context_effect={'bend_rules': True} if bend_rules else None)
                self._keep_debug_pub.publish(String(data=json.dumps(bundle, default=float)))
            elif mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab'):
                if (mode in ('route_a', 'route_b', 'route_ab')
                        and self._route_follower is not None
                        and not simulation_ground_allowed(
                            source=self.get_parameter('camera_ground_source').value,
                            simulation_enabled=self.get_parameter('allow_simulation_ground').value,
                            use_sim_time=self.get_parameter('use_sim_time').value)):
                    # A geometry change invalidates the static map/odom anchor.
                    # Require a fresh node instead of reviving stale memory.
                    self._route_follower = None
                    self.get_logger().warning(
                        f'{mode} simulation context changed; route follower revoked', once=True)
                ground = self._ground(frame.shape[1], frame.shape[0])
                lane_kwargs = dict(
                    bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    lane_half_width_m=float(self.get_parameter('lane_half_width_m').value),
                    roi_top_fraction=float(self.get_parameter('camera_roi_top_fraction').value),
                    roi_bottom_fraction=float(
                        self.get_parameter('camera_roi_bottom_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value),
                )
                if mode == 'centre':
                    image_stamp = (float(msg.header.stamp.sec)
                                   + float(msg.header.stamp.nanosec) * 1e-9)
                    observation = self._centre_tracker.update(
                        image_stamp,
                        pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                elif mode == 'edge_left':
                    image_stamp = (float(msg.header.stamp.sec)
                                   + float(msg.header.stamp.nanosec) * 1e-9)
                    observation = self._edge_follower.update(
                        image_stamp,
                        pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                elif mode in ('route_a', 'route_b', 'route_ab'):
                    if self._route_follower is not None:
                        image_stamp = (float(msg.header.stamp.sec)
                                       + float(msg.header.stamp.nanosec) * 1e-9)
                        observation = self._route_follower.update(
                            image_stamp,
                            pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                            frame, ground, **lane_kwargs)
                        if mode == 'route_a' and self._route_follower.last.get('reason') == 'washed':
                            observation = None
                            quality = dict(valid=False, reason='overexposed')
                elif bool(self.get_parameter('lane_corner_turning').value):
                    image_stamp = (float(msg.header.stamp.sec)
                                   + float(msg.header.stamp.nanosec) * 1e-9)
                    observation = self._corner_tracker.update(
                        image_stamp,
                        pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                else:
                    observation = detect_lane_centre(frame, ground, **lane_kwargs)
            else:
                raise ValueError(f'unsupported camera_lane_mode {mode!r}')
        except ValueError as exc:
            observation = None
            self.get_logger().warning(f'invalid camera line frame: {exc}')
        source_stamp = (float(msg.header.stamp.sec)
                        + float(msg.header.stamp.nanosec) * 1e-9)
        containment = None
        if mode == 'keep' and observation is not None:
            containment = containment_payload(
                self._lane_keeper.last, ground, stamp=source_stamp,
                source=str(self.get_parameter('camera_ground_source').value).upper(),
                camera_x=self._lane_keeper._x_offset, geometry_bounds=self._ground_error,
                paint_half_width_m=self._paint_half_width_m)
        self._publish('CAMERA_LINE', observation, stamp=source_stamp,
                      quality=quality, containment=containment,
                      route_context_seq=route_context_seq)
        self._publish_debug(msg, frame, observation)

    def _publish_debug(self, msg, frame, observation) -> None:
        """Observation only: a picture of the decision just published.

        Never allowed to take line/observation down with it (D-143): any
        render or encode failure here is caught, logged (throttled), and
        skipped, so this frame's overlay is lost but every later
        line/observation still publishes."""
        if self._debug_pub is None or frame is None:
            return
        stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        max_hz = float(self.get_parameter('debug_overlay_max_hz').value)
        if not next_publish_due(self._debug_last_s, stamp, max_hz):
            return
        self._debug_last_s = stamp
        mode = str(self.get_parameter('camera_lane_mode').value)
        follower = {
            'centre': self._centre_tracker,
            'edge_left': self._edge_follower,
            'route_a': self._route_follower,
            'route_b': self._route_follower,
            'route_ab': self._route_follower,
        }.get(mode)
        if follower is None:
            return
        try:
            image = render_debug(
                frame, follower, observation, mode=mode,
                pose=pose_if_fresh(self._odom_pose, self._odom_stamp, stamp),
                graph=self._debug_graph,
                bright_threshold=int(self.get_parameter('camera_bright_threshold').value))
            ok, data = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                return
            out = CompressedImage()
            out.header = msg.header
            out.format = 'jpeg; overlay=lane-debug-v1'
            out.data = data.tobytes()
            self._debug_pub.publish(out)
        except Exception as exc:  # noqa: BLE001 - the overlay must never be fatal.
            self.get_logger().warning(
                f'debug overlay render/publish failed: {exc}', throttle_duration_sec=5.0)

    def _on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        q = pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        self._odom_pose = (float(pose.position.x), float(pose.position.y), yaw)
        # The header stamp, not arrival time: edge_left compares it with the image stamp (dead or delayed odom is no pose).
        self._odom_twist = (float(msg.twist.twist.linear.x), float(msg.twist.twist.angular.z))
        self._odom_stamp = (float(msg.header.stamp.sec)
                            + float(msg.header.stamp.nanosec) * 1e-9)
        self._odom_history.add(self._odom_stamp, *self._odom_pose)

    def _on_cmd_vel(self, msg: Twist) -> None:   # Twist has no header: stamped on arrival (node clock, sim time in SIM)
        self._cmd_twist, self._cmd_stamp = (msg.linear.x, msg.angular.z), self.get_clock().now().nanoseconds * 1e-9

    def _on_camera_controls(self, msg: String) -> None:
        summary = str(msg.data)
        self._camera_controls_stable = (
            summary.startswith('exposure=') or summary.startswith('v4l2 exposure='))


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
