#!/usr/bin/env python3
"""Publish normalized white-line evidence from IR reflectance or camera frames.

This node owns no motion output. CORE chooses exactly one source and remains
the sole final ``cmd_vel`` publisher (D-143).
"""

import json
import math
import os

import cv2
import rclpy
import yaml
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String, UInt16MultiArray

from . import executor_choice
from .calibrated_values import calibrated
from .sensing.perception.camera_ground import nominal_ground_plane, simulation_ground_plane
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
from .sensing.perception.lane_debug import next_publish_due, render_debug
from .sensing.perception.lane_containment import containment_payload, geometry_error
from .sensing.perception.paint_localizer import PaintMap
from .sensing.perception.route_camera import RouteCameraFollower
from .sensing.perception.route_hybrid import RouteHybridFollower
from .sensing.perception.route_map import RouteMapFollower

#: Fixed at startup: the edge follower and the odom subscription are built
#: from these once, so a later change would silently run the wrong pipeline.
_READ_ONLY = ParameterDescriptor(read_only=True)
#: 'keep' mode: a gap between camera frames longer than this resets the keeper.
KEEP_MAX_FRAME_GAP_S = 0.5


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
        # 'line' follows one bright line; 'lane' keeps the centre between two
        # boundary lines; 'edge_left' holds the lane's left boundary a
        # half-width off in bird's-eye view (bends, arcs). Both lane modes need
        # a metric ground plane, edge_left also odometry (fail-closed without).
        # 'centre' follows the centre line between both boundaries (fallback ladder).
        # 'between' keeps the midpoint of the two boundary lines in image
        # space (no ground plane, no odometry).
        # 'keep' keeps the middle of the lane from ground-plane boundary lines
        # found per frame (no odometry): the real-robot lane keeper (D-364 §2),
        # on camera_ground_source NOMINAL + allow_nominal_ground, or GAZEBO.
        # 'route_a'/'route_b' are the junction prototypes: route-driven
        # manoeuvres over the centre-line tracker (A) and planned-route
        # pursuit from a paint-localised pose (B). 'route_ab' is their
        # hybrid: A's manoeuvres placed by B's paint-localised pose. All
        # need lane_graph_path/route/route_start; fail closed without them.
        # D-408: keep-mode paint source: threshold (default) | denoise | learned (+ denoise fallback).
        self.declare_parameter('paint_source', 'threshold', _READ_ONLY)
        self.declare_parameter('learned_lane_pointer', '', _READ_ONLY)
        self.declare_parameter('learned_paint_stale_s', 0.6, _READ_ONLY)
        # D-408 CPU: infer on every Nth keep frame (the mask is reused in between), on 1 thread.
        self.declare_parameter('learned_paint_every_n', 2, _READ_ONLY)
        self.declare_parameter('learned_paint_threads', 1, _READ_ONLY)
        # Turning moves the image between frames: above this |odom wz| (or with no fresh odom) the
        # mask is not reused (cadence 1: every frame infers, a late mask falls back to denoise).
        self.declare_parameter('learned_paint_reuse_max_wz', 0.15)
        self.declare_parameter('camera_lane_mode', 'line', _READ_ONLY)
        self.declare_parameter('lane_half_width_m', 0.0925)
        self.declare_parameter('camera_roi_bottom_fraction', 1.0)
        # 'between' only: bottom band start (keeps white walls out) and the
        # lane width as a frame fraction until both boundaries are seen.
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
        # Lane mode only: odometry-bounded 90 deg corner turning. Off by
        # default; without odometry the tracker never leaves FOLLOW.
        self.declare_parameter('lane_corner_turning', False, _READ_ONLY)
        self.declare_parameter('camera_x_offset_m', 0.0)
        self.declare_parameter('debug_overlay', False, _READ_ONLY)
        self.declare_parameter('debug_overlay_max_hz', 5.0)
        self.declare_parameter('debug_lane_graph', '')
        # route_a/route_b/route_ab only. route and route_start are declared by type,
        # not value: an empty Python list default cannot be typed, and the
        # config file's own empty-list override (line_follow.yaml) needs a
        # declared element type (string / double) to resolve against.
        self.declare_parameter('lane_graph_path', '', _READ_ONLY)
        self.declare_parameter('route', Parameter.Type.STRING_ARRAY, _READ_ONLY)
        self.declare_parameter('route_start', Parameter.Type.DOUBLE_ARRAY, _READ_ONLY)

        self._ir_calibration = None
        self._ir_calibration_revision = None
        self._camera_controls_stable = False
        self._simulation_ground_key = None
        self._simulation_ground = None
        self._nominal_profile_cache = None
        self._ground_error = None
        self._odom_pose = None
        self._odom_stamp = None
        self._odom_wz = None
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
        self._keep_last_stamp = None
        self._lane_keeper = LaneKeeper(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value),
            corner_turning=bool(self.get_parameter('lane_corner_turning').value))
        self._paint_worker = self._build_paint_worker()
        self._route_follower = None
        camera_lane_mode = str(self.get_parameter('camera_lane_mode').value)
        if camera_lane_mode in ('route_a', 'route_b', 'route_ab'):
            self._route_follower = self._build_route_follower(camera_lane_mode)
        self._debug_pub = None
        self._debug_last_s = None
        self._debug_graph = None
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
        if mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab'):
            self.create_subscription(
                Odometry, 'odom', self._on_odom, qos_profile_sensor_data)
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

    def _publish(self, source, observation, *, stamp=None, quality=None, containment=None) -> None:
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
        self.observation_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

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
        from .sensing.perception.learned.paint_worker import LearnedPaintWorker
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
                                  warn=self.get_logger().warning)

    def _paint_for(self, frame, ground, stamp=None):
        """(paint mask or None, source actually used) for one keep frame (D-408)."""
        source = str(self.get_parameter('paint_source').value)
        if source == 'threshold' or ground is None:
            if self._paint_worker is not None:
                self._paint_worker.reset()
            return None, 'threshold'
        if source == 'learned' and self._paint_worker is not None:
            every_n = int(self.get_parameter('learned_paint_every_n').value)
            wz = self._odom_wz
            fresh = (stamp is not None and self._odom_stamp is not None
                     and abs(stamp - self._odom_stamp) <= KEEP_MAX_FRAME_GAP_S)
            if not fresh or wz is None or abs(wz) > float(self.get_parameter('learned_paint_reuse_max_wz').value):
                every_n = 1
            mask = self._paint_worker.mask_for(
                frame, every_n, stamp, clean=lambda m: clean_learned_mask(m, ground.horizon_row))
            if mask is not None:
                return mask, 'learned'
        return denoise_white_mask(frame, ground.horizon_row), (
            'denoise' if source == 'denoise' else 'denoise_fallback')

    def _on_camera(self, msg: Image) -> None:
        observation = None
        frame = None
        mode = None
        ground = None
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
                # A camera gap (or the first keep frame of this node) starts
                # the keeper afresh: sides and steering remembered from before
                # the gap may belong to another place.
                image_stamp = (float(msg.header.stamp.sec)
                               + float(msg.header.stamp.nanosec) * 1e-9)
                if (self._keep_last_stamp is None
                        or not 0.0 <= image_stamp - self._keep_last_stamp <= KEEP_MAX_FRAME_GAP_S):
                    self._lane_keeper.reset()
                    if self._paint_worker is not None:
                        self._paint_worker.reset()
                self._keep_last_stamp = image_stamp
                ground = self._ground(frame.shape[1], frame.shape[0])
                paint, paint_used = self._paint_for(frame, ground, image_stamp)
                observation = self._lane_keeper.update(
                    frame, ground, paint_mask=paint,
                    lane_half_width_m=float(self.get_parameter('lane_half_width_m').value))
                bundle = dict(self._lane_keeper.last, paint_source_used=paint_used,
                              paint_source_requested=str(self.get_parameter('paint_source').value),
                              paint_model_revision=(self._paint_worker.used_model_revision
                                                    if paint_used == 'learned' and self._paint_worker is not None
                                                    else None),
                              image_size=[frame.shape[1], frame.shape[0]],
                              camera_geometry_source=str(self.get_parameter('camera_ground_source').value).upper(),
                              # D-492: CORE reports junction_turn only from live keep evidence.
                              corner_turning=bool(self.get_parameter('lane_corner_turning').value),
                              ground=self._ground_label(),
                              stamp=float(msg.header.stamp.sec)
                              + float(msg.header.stamp.nanosec) * 1e-9)
                self._keep_debug_pub.publish(String(data=json.dumps(bundle, default=float)))
            elif mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab'):
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
                camera_x=self._lane_keeper._x_offset, geometry_bounds=self._ground_error)
        self._publish('CAMERA_LINE', observation, stamp=source_stamp, containment=containment)
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
        # The header stamp, not arrival time: edge_left compares it with the
        # image stamp, so dead or delayed odometry is no pose.
        self._odom_wz = float(msg.twist.twist.angular.z)
        self._odom_stamp = (float(msg.header.stamp.sec)
                            + float(msg.header.stamp.nanosec) * 1e-9)

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
