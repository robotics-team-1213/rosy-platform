#!/usr/bin/env python3
"""ROS adapter for D-395 fleet-assisted localization (P2-3); every decision is `LocAssist`'s.

Topics (robot namespace, JSON in std_msgs/String, contract
docs/plans/2026-10-01-d395-phase2-interfaces.md §1):
  out  localization/state, localization/candidates, localization/result,
       initialpose (PoseWithCovarianceStamped, map frame, only on an accepted decision)
  in   map, scan, amcl_pose, camera/front (reference-square sightings),
       safety/pickup, localization/decision, localization/suspect

Paint: no ROS topic carries the camera's paint points (they stay inside
line_observer's bird's-eye keep/edge pipeline), so every `paint_score` is None.

The search runs on one worker thread over a 2 cm max-pooled copy of the map;
the clear-footprint mask is computed once per map. A search longer than
`search_budget_s` is logged: numpy cannot be pre-empted, so the budget is a
measurement to act on (Pi), not a cut-off.
"""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import Bool, String
from tf2_ros import TransformListener

from . import executor_choice
from .calibrated_values import calibrated
from .loc_assist import LocAssist, lane_rules_near, pooled_grid, search
from .sensing.body import URDF_RADIUS
from .sensing.loc_candidates import Mount, reference_squares
from .sensing.localization import MapAgreement, planar_yaw
from .sensing.perception.camera_ground import nominal_ground_plane, simulation_ground_plane
from .sensing.perception.reference_square import HsvSquareDetector
from .tf_buffer import RobotTransformBuffer

PARAMETERS = [
    ('map_yaml', ''), ('lane_rules_file', ''), ('search_resolution', .02), ('wall_tolerance', .04),
    ('robot_radius', URDF_RADIUS), ('scan_stride', 4), ('candidate_minimum_fit', .9),
    ('search_budget_s', 3.), ('retry_s', 5.), ('rereport_s', 2.), ('hold_s', 3.), ('minimum_fit', .85),
    ('square_period_s', .5), ('sighting_max_age_s', 1.),
    ('camera_ground_source', 'PINKY'), ('allow_simulation_ground', False),
    ('allow_nominal_ground', False), ('nominal_camera_profile_path', ''), ('camera_x_offset_m', 0.),
    ('gazebo_camera_height_m', 0.), ('gazebo_camera_pitch_rad', 0.), ('gazebo_camera_hfov_rad', 0.),
    ('gazebo_camera_max_range_m', .6),
]


def yaw(q):
    return planar_yaw(q.x, q.y, q.z, q.w)


class LocAssistNode(Node):
    def __init__(self):
        super().__init__('loc_assist')
        for name, value in PARAMETERS:
            self.declare_parameter(name, value)
        ids = iter(range(1, 1 << 62))
        boot = time.strftime('%H%M%S')
        self.core = LocAssist(lambda: f'{boot}-{next(ids)}', rereport_s=self.p('rereport_s'),
                              retry_s=self.p('retry_s'), hold_s=self.p('hold_s'),
                              min_fit=self.p('minimum_fit'))
        self.field = self.clear = self.scan = None
        self.generation = 0
        self.squares = self._squares()
        self.detector = HsvSquareDetector(self.p('camera_x_offset_m'))
        self.sightings, self.sighted_at, self.square_at = [], -math.inf, -math.inf
        self.ground_key = self.ground = self.nominal = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.search = None
        self.tf = RobotTransformBuffer(self)
        self.listener = TransformListener(self.tf, self)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.pub = {'state': self.create_publisher(String, 'localization/state', latched),
                    'candidates': self.create_publisher(String, 'localization/candidates', latched),
                    'result': self.create_publisher(String, 'localization/result', 10)}
        self.initial_pose = self.create_publisher(PoseWithCovarianceStamped, 'initialpose', 10)
        self.create_subscription(OccupancyGrid, 'map', self.on_map, latched)
        self.create_subscription(LaserScan, 'scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, 'amcl_pose', self.on_pose, latched)
        self.create_subscription(Image, 'camera/front', self.on_camera, qos_profile_sensor_data)
        self.create_subscription(Bool, 'safety/pickup', self.on_pickup, 1)
        self.create_subscription(String, 'localization/decision', self.on_decision, 5)
        self.create_subscription(String, 'localization/suspect', self.on_suspect, 5)
        self.create_timer(.1, self.tick)

    def p(self, name):
        return self.get_parameter(name).value

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _squares(self):
        path = self.p('lane_rules_file') or lane_rules_near(self.p('map_yaml'))
        if not path:
            self.get_logger().info('no lane_rules.yaml: slot candidates off, global search only')
            return []
        try:
            with open(path, encoding='utf-8') as handle:
                squares = reference_squares(yaml.safe_load(handle))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            self.get_logger().warning(f'reference squares unreadable ({exc}); global search only')
            return []
        self.get_logger().info(f'{len(squares)} reference squares from {path}')
        return squares

    # --- inputs -------------------------------------------------------------
    def on_map(self, msg):
        self.field = self.clear = None
        self.generation += 1
        info = msg.info
        try:
            rotation = yaw(info.origin.orientation)
        except ValueError:
            return
        if (msg.header.frame_id != 'map' or not math.isfinite(info.resolution) or info.resolution <= 0 or
                info.width <= 0 or info.height <= 0 or info.width * info.height != len(msg.data) or
                not all(math.isfinite(v) for v in (info.origin.position.x, info.origin.position.y)) or
                abs(rotation) > 1e-6):
            self.get_logger().warning('map rejected: needs an unrotated finite map-frame grid')
            return
        grid, resolution = pooled_grid(np.array(msg.data, dtype=np.int8).reshape(info.height, info.width),
                                       info.resolution, self.p('search_resolution'))
        self.field = MapAgreement(grid, resolution, (info.origin.position.x, info.origin.position.y),
                                  self.p('wall_tolerance'))

    def scan_arrays(self, scan):
        stride = max(1, int(self.p('scan_stride')))
        ranges = np.asarray(scan.ranges, dtype=float)[::stride]
        angles = scan.angle_min + np.arange(len(scan.ranges))[::stride] * scan.angle_increment
        return np.where((ranges < scan.range_max) & (ranges >= scan.range_min), ranges, np.nan), angles

    def on_scan(self, msg):
        self.scan = msg
        machine = self.core.machine
        if self.field is None or (machine.check is None and not machine.autonomy_allowed):
            return
        try:
            tf = self.tf.lookup_transform('map', msg.header.frame_id, rclpy.time.Time.from_msg(msg.header.stamp))
        except Exception:
            return                          # no fit this scan; a long gap fails the check on tick
        tr = tf.transform.translation
        ranges, angles = self.scan_arrays(msg)
        fit = self.field.score((tr.x, tr.y, yaw(tf.transform.rotation)), ranges, angles)
        self.publish(self.core.on_fit(self.now(), fit))

    def on_pose(self, msg):
        p = msg.pose.pose
        try:
            self.core.on_amcl_pose((p.position.x, p.position.y, yaw(p.orientation)))
        except ValueError:
            pass

    def on_pickup(self, msg):
        self.publish(self.core.on_pickup(self.now(), bool(msg.data)))

    def _json(self, msg, topic):
        try:
            return json.loads(msg.data)
        except (TypeError, ValueError):
            self.get_logger().warning(f'{topic}: not JSON, ignored')
            return None

    def on_decision(self, msg):
        payload = self._json(msg, 'localization/decision')
        if payload is not None:
            self.publish(self.core.on_decision(self.now(), payload))

    def on_suspect(self, msg):
        payload = self._json(msg, 'localization/suspect')
        if payload is not None:
            self.publish(self.core.on_suspect(self.now(), payload))

    def on_camera(self, msg):
        now = self.now()
        if self.core.machine.autonomy_allowed or now - self.square_at < self.p('square_period_s'):
            return
        self.square_at = now
        if msg.encoding not in ('bgr8', 'rgb8'):
            return
        pixels = np.frombuffer(msg.data, dtype=np.uint8)
        if pixels.size != int(msg.height) * int(msg.width) * 3:
            return
        frame = pixels.reshape((int(msg.height), int(msg.width), 3))
        frame = np.ascontiguousarray(frame[:, :, ::-1] if msg.encoding == 'rgb8' else frame)
        ground = self._ground(frame.shape[1], frame.shape[0])
        if ground is not None:
            self.sightings, self.sighted_at = self.detector.detect(frame, ground), now

    def _ground(self, width, height):
        source = str(self.p('camera_ground_source'))
        key = (source, width, height)
        if key == self.ground_key:
            return self.ground
        if source.strip().upper() == 'NOMINAL':
            if self.nominal is None:
                path = str(self.p('nominal_camera_profile_path'))
                try:
                    with open(path, encoding='utf-8') as handle:
                        static = yaml.safe_load(handle) or {}
                except (OSError, yaml.YAMLError):
                    static = {}
                self.nominal, origin = calibrated('camera_profile', static, static_source=path or 'no file')
                self.get_logger().info(f'camera profile from {origin}')
            self.ground = nominal_ground_plane(source=source, allowed=bool(self.p('allow_nominal_ground')),
                                               width_px=width, height_px=height, profile=self.nominal)
        else:
            self.ground = simulation_ground_plane(
                source=source, simulation_enabled=bool(self.p('allow_simulation_ground')),
                use_sim_time=bool(self.p('use_sim_time')), width_px=width, height_px=height,
                height_m=self.p('gazebo_camera_height_m'), pitch_rad=self.p('gazebo_camera_pitch_rad'),
                hfov_rad=self.p('gazebo_camera_hfov_rad'), max_range_m=self.p('gazebo_camera_max_range_m'))
        self.ground_key = key
        return self.ground

    # --- search and timer ---------------------------------------------------
    def odom(self):
        try:
            tf = self.tf.lookup_transform('odom', 'base_link', rclpy.time.Time())
            tr = tf.transform.translation
            return tr.x, tr.y, yaw(tf.transform.rotation)
        except Exception:
            return None

    def start_search(self, now, odom):
        try:
            mount_tf = self.tf.lookup_transform('base_link', self.scan.header.frame_id, rclpy.time.Time())
            t = mount_tf.transform.translation
            mount = Mount(t.x, t.y, yaw(mount_tf.transform.rotation))
        except Exception:
            return
        ranges, angles = self.scan_arrays(self.scan)
        self.core.search_started(now, odom)
        field, clear, generation, started = self.field, self.clear, self.generation, time.monotonic()
        squares, radius, minimum = self.squares, self.p('robot_radius'), self.p('candidate_minimum_fit')

        def run():
            found, objects, mask = search(field, clear, squares, ranges, angles, radius, mount, minimum)
            return found, objects, mask, generation, time.monotonic() - started
        self.search = self.pool.submit(run)

    def finish_search(self, now):
        future, self.search = self.search, None
        try:
            found, objects, mask, generation, elapsed = future.result()
        except Exception as exc:
            self.get_logger().warning(f'candidate search failed: {exc!r}')
            found, objects, mask, generation, elapsed = [], [], None, -1, 0.
        if generation == self.generation:
            self.clear = mask
        budget = self.p('search_budget_s')
        log = self.get_logger().warning if elapsed > budget else self.get_logger().info
        log(f'candidate search {elapsed:.2f} s (budget {budget:.1f} s): {len(found)} candidates')
        fresh = self.sightings if now - self.sighted_at <= self.p('sighting_max_age_s') else []
        # A new map while searching: no odom discards the result and the next tick searches again.
        odom = self.odom() if generation in (self.generation, -1) else None
        self.publish(self.core.search_finished(now, odom, found, objects, fresh))

    def tick(self):
        now = self.now()
        if self.search is not None and self.search.done():
            self.finish_search(now)
        self.publish(self.core.tick(now))
        if self.search is None and self.field is not None and self.scan is not None:
            odom = self.odom()
            if odom is not None and self.core.search_due(now, odom):
                self.start_search(now, odom)

    # --- outputs ------------------------------------------------------------
    def publish(self, outputs):
        for kind, payload in outputs:
            if kind == 'inject':
                self.inject(payload)
            else:
                self.pub[kind].publish(String(data=json.dumps(payload, sort_keys=True)))

    def inject(self, injection):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self.get_clock().now().to_msg()
        x, y, heading = injection.pose
        msg.pose.pose.position.x, msg.pose.pose.position.y = x, y
        msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(heading / 2), math.cos(heading / 2)
        msg.pose.covariance[0] = msg.pose.covariance[7] = injection.xy_std ** 2
        msg.pose.covariance[35] = injection.yaw_std ** 2
        self.initial_pose.publish(msg)
        self.get_logger().info(f'initialpose from {injection.source} decision {injection.request_id}: '
                               f'({x:.3f}, {y:.3f}, {heading:.3f}); 3 s check started')


def main():
    rclpy.init()
    node = LocAssistNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.pool.shutdown(wait=False, cancel_futures=True)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
