#!/usr/bin/env python3
"""ROS adapter for D-395 fleet-assisted localization (P2-3); every decision is `LocAssist`'s.

Topics (robot namespace, JSON in std_msgs/String, contract
docs/plans/2026-10-01-d395-phase2-interfaces.md §1):
  out  localization/state, localization/candidates, localization/result,
       initialpose (PoseWithCovarianceStamped, map frame, only on an accepted decision)
  in   map, scan, amcl_pose, camera/front (reference-square sightings, paint points),
       odom (twist: a search waits until the robot is still),
       safety/pickup, localization/decision, localization/suspect

Paint: the camera frame already decoded for squares also gives floor paint
points (`camera_paint_points`, the keep mode's front end) at the same 2 Hz;
each candidate gets `paint_score` against the map bundle's STL paint map. No
bundle STL (a site map without it) or no ground plane: paint_score is None.

While LOCALIZED, each state message (2 Hz) also carries the unmapped objects of a
full scan at the AMCL pose, with that scan's stamp (D-395 rev. 4 §5, S1 R1).

The search runs on one worker thread over a 2 cm max-pooled copy of the map;
the clear-footprint mask is computed once per map. A search longer than
`search_budget_s` is logged: numpy cannot be pre-empted, so the budget is a
measurement to act on (Pi), not a cut-off.
"""
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import Bool, String
from tf2_ros import TransformListener

from . import executor_choice
from .calibrated_values import calibrated
from .loc_assist import LocAssist, lane_rules_near, localized_objects, pooled_grid, search
from .sensing.body import URDF_RADIUS
from .sensing.loc_candidates import Mount, reference_squares
from .sensing.localization import MapAgreement, planar_yaw
from .sensing.perception.camera_ground import nominal_ground_plane, simulation_ground_plane
from .sensing.perception.lane_bev import BirdsEye
from .sensing.perception.paint_hypothesis import camera_paint_points, paint_score
from .sensing.perception.paint_localizer import PaintMap
from .sensing.perception.reference_square import HsvSquareDetector
from .tf_buffer import RobotTransformBuffer

PARAMETERS = [
    ('map_yaml', ''), ('lane_rules_file', ''), ('search_resolution', .02), ('wall_tolerance', .04),
    ('robot_radius', URDF_RADIUS), ('scan_stride', 4), ('candidate_minimum_fit', .9),
    ('search_budget_s', 3.), ('retry_s', 5.), ('rereport_s', 2.), ('hold_s', 3.), ('minimum_fit', .85),
    # Scan silence the 3 s check tolerates: 1 s rides out executor stalls under load
    # (WSL, a loaded Pi) while a 10 Hz lidar still feeds ~10 fits per second.
    ('max_gap_s', 1.),
    ('square_period_s', .5), ('sighting_max_age_s', 1.),
    ('camera_ground_source', 'PINKY'), ('allow_simulation_ground', False),
    ('allow_nominal_ground', False), ('nominal_camera_profile_path', ''), ('camera_x_offset_m', 0.),
    ('gazebo_camera_height_m', 0.), ('gazebo_camera_pitch_rad', 0.), ('gazebo_camera_hfov_rad', 0.),
    ('gazebo_camera_max_range_m', .6),
]


def yaw(q):
    return planar_yaw(q.x, q.y, q.z, q.w)


def search_job(stopping, bundle, generation, field, *search_args):
    """Worker thread: the one-time paint map load, then the candidate search.

    No logging here: notes go back to `finish_search` on the executor. A stop
    set between the phases (shutdown) skips the search."""
    notes, paint_map = [], None
    if bundle:                              # once, off the executor: the STL paint raster takes seconds
        try:
            paint_map = PaintMap.from_bundle(bundle)
        except Exception as exc:
            notes.append(f'no paint map from {bundle} ({exc!r}); paint_score stays None')
    if stopping.is_set():
        return [], [], None, -1, 0., notes, paint_map
    started = time.monotonic()
    found, objects, mask = search(field, *search_args)
    return found, objects, mask, generation, time.monotonic() - started, notes, paint_map


class LocAssistNode(Node):
    def __init__(self):
        super().__init__('loc_assist')
        for name, value in PARAMETERS:
            self.declare_parameter(name, value)
        ids = iter(range(1, 1 << 62))
        boot = time.strftime('%H%M%S')
        self.core = LocAssist(lambda: f'{boot}-{next(ids)}', rereport_s=self.p('rereport_s'),
                              retry_s=self.p('retry_s'), hold_s=self.p('hold_s'),
                              min_fit=self.p('minimum_fit'), max_gap_s=self.p('max_gap_s'))
        self.field = self.clear = self.scan = None
        self.generation = 0
        self.squares = self._squares()
        self.detector = HsvSquareDetector(self.p('camera_x_offset_m'))
        self.sightings, self.sighted_at, self.square_at = [], -math.inf, -math.inf
        self.paint, self.paint_map, self.paint_tried, self.view = None, None, False, None
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
        self.camera = None                  # camera/front exists only outside LOCALIZED (sync_camera)
        self.stopping = threading.Event()   # set by main() before the pool shuts down
        # Always held: a 20-50 Hz twist is cheap, and every search waits on it (S1 re-run R3).
        self.create_subscription(Odometry, 'odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(Bool, 'safety/pickup', self.on_pickup, 1)
        self.create_subscription(String, 'localization/decision', self.on_decision, 5)
        self.create_subscription(String, 'localization/suspect', self.on_suspect, 5)
        self.create_subscription(String, 'localization/mission', self.on_mission, 5)
        self.sync_camera()
        self.create_timer(.1, self.tick)

    def p(self, name):
        return self.get_parameter(name).value

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _squares(self):
        path = self.p('lane_rules_file') or lane_rules_near(self.p('map_yaml'))
        self.bundle = os.path.dirname(path) if path else None
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

    def scan_arrays(self, scan, stride=None):
        stride = max(1, int(self.p('scan_stride') if stride is None else stride))
        ranges = np.asarray(scan.ranges, dtype=float)[::stride]
        angles = scan.angle_min + np.arange(len(scan.ranges))[::stride] * scan.angle_increment
        return np.where((ranges < scan.range_max) & (ranges >= scan.range_min), ranges, np.nan), angles

    def on_scan(self, msg):
        self.scan = msg
        machine = self.core.machine
        if self.field is None or (machine.check is None and not machine.autonomy_allowed):
            return
        # odom->sensor at the scan stamp, then AMCL's *latest* map->odom. AMCL stamps
        # map->odom transform_tolerance ahead (1.0 s in sim, 0.3 s on the device), so a
        # map lookup at the scan stamp returns the correction from ~1 s earlier: for that
        # long after /initialpose the 3 s check scored the pre-injection pose (fit ~0.01)
        # and failed at its 0.5 s settle (S1 finding 1). settle_s covers AMCL's own
        # processing of /initialpose; a pose AMCL never applied still fails.
        try:
            tf = self.tf.lookup_transform_full('map', rclpy.time.Time(), msg.header.frame_id,
                                               rclpy.time.Time.from_msg(msg.header.stamp), 'odom')
        except Exception:
            return                          # no fit this scan; a long gap fails the check on tick
        tr = tf.transform.translation
        sensor = (tr.x, tr.y, yaw(tf.transform.rotation))
        ranges, angles = self.scan_arrays(msg)
        fit = self.field.score(sensor, ranges, angles)
        now = self.now()
        self.publish(self.core.on_fit(now, fit))
        if self.core.objects_due(now):
            self.report_objects(now, msg, sensor)

    def report_objects(self, now, msg, sensor):
        """D-395 rev. 4 §5 (S1 R1): a LOCALIZED robot reports what the map does not explain,
        from every beam at its map pose, so Fleet can check the other robots against it."""
        try:
            mount_tf = self.tf.lookup_transform('base_link', msg.header.frame_id, rclpy.time.Time())
        except Exception:
            return
        t = mount_tf.transform.translation
        mount = Mount(t.x, t.y, yaw(mount_tf.transform.rotation))
        objects = localized_objects(self.field, sensor, *self.scan_arrays(msg, 1), mount,
                                    self.p('robot_radius'))
        self.core.on_objects(now, rclpy.time.Time.from_msg(msg.header.stamp).nanoseconds * 1e-9, objects)

    def on_pose(self, msg):
        p = msg.pose.pose
        try:
            self.core.on_amcl_pose((p.position.x, p.position.y, yaw(p.orientation)))
        except ValueError:
            pass

    def on_odom(self, msg):
        t = msg.twist.twist
        self.core.on_twist(self.now(), math.hypot(t.linear.x, t.linear.y), t.angular.z)

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
            out = self.core.on_decision(self.now(), payload)
            if not out:
                self.get_logger().debug('repeat of the decision under its 3 s check; ignored')
            self.publish(out)

    def on_suspect(self, msg):
        payload = self._json(msg, 'localization/suspect')
        if payload is not None:
            self.publish(self.core.on_suspect(self.now(), payload))

    def on_mission(self, msg):
        payload = self._json(msg, 'localization/mission')
        if payload is not None:
            self.core.on_mission(self.now(), payload)

    def on_camera(self, msg):
        now = self.now()
        if not self.core.camera_wanted or now - self.square_at < self.p('square_period_s'):
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
            if self.view is None or self.view[0] != self.ground_key:
                self.view = (self.ground_key, BirdsEye(ground, frame.shape[1], frame.shape[0],
                                                       self.p('camera_x_offset_m')))
            self.paint = camera_paint_points(frame, ground, self.p('camera_x_offset_m'), self.view[1])

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
        full = self.scan_arrays(self.scan, 1)   # peer objects: every beam (S1 finding 2)
        self.core.search_started(now, odom)
        field, clear, generation = self.field, self.clear, self.generation
        squares, radius, minimum = self.squares, self.p('robot_radius'), self.p('candidate_minimum_fit')

        bundle, self.paint_tried = (None if self.paint_tried else self.bundle), True
        self.search = self.pool.submit(search_job, self.stopping, bundle, generation, field, clear, squares,
                                       ranges, angles, radius, mount, minimum, full)

    def finish_search(self, now):
        future, self.search = self.search, None
        try:
            found, objects, mask, generation, elapsed, notes, paint_map = future.result()
        except Exception as exc:
            self.get_logger().warning(f'candidate search failed: {exc!r}')
            found, objects, mask, generation, elapsed, notes, paint_map = [], [], None, -1, 0., [], None
        for note in notes:
            self.get_logger().warning(note)
        self.paint_map = paint_map or self.paint_map
        if generation == self.generation:
            self.clear = mask
        budget = self.p('search_budget_s')
        log = self.get_logger().warning if elapsed > budget else self.get_logger().info
        log(f'candidate search {elapsed:.2f} s (budget {budget:.1f} s): {len(found)} candidates')
        recent = now - self.sighted_at <= self.p('sighting_max_age_s')
        scores = None
        if recent and self.paint is not None and self.paint_map is not None:
            scores = [paint_score(self.paint_map, self.paint, (c.x, c.y, c.yaw)) for c in found]
        # A new map while searching: no odom discards the result and the next tick searches again.
        odom = self.odom() if generation in (self.generation, -1) else None
        # The core drops camera evidence seen before the search started (evidence_s).
        self.publish(self.core.search_finished(now, odom, found, objects, self.sightings if recent else [],
                                               scores, evidence_s=self.sighted_at if recent else None))

    def sync_camera(self):
        """Hold camera/front only while square/paint evidence can matter (not LOCALIZED)."""
        if self.core.camera_wanted and self.camera is None:
            self.camera = self.create_subscription(Image, 'camera/front', self.on_camera, qos_profile_sensor_data)
        elif not self.core.camera_wanted and self.camera is not None:
            self.destroy_subscription(self.camera)
            self.camera = None

    def tick(self):
        now = self.now()
        if self.search is not None and self.search.done():
            self.finish_search(now)
        self.publish(self.core.tick(now))
        self.sync_camera()
        if self.search is None and self.field is not None and self.scan is not None:
            odom = self.odom()
            if odom is not None and self.core.search_due(now, odom):
                if self.core.settle_timed_out:
                    self.get_logger().warning(f'search after the settle cap ({self.core.settle_timed_out}): '
                                              'the robot was not seen still; searching anyway')
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
        node.stopping.set()
        node.pool.shutdown(wait=False, cancel_futures=True)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
