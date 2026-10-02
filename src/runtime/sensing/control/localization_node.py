#!/usr/bin/env python3
"""ROS adapter for AMCL confidence and stationary updates; D-395 owns pose injection."""
import json
import math
import numpy as np
import rclpy
from . import executor_choice
from .tf_buffer import RobotTransformBuffer
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String, Bool
from std_srvs.srv import Empty
from tf2_ros import TransformListener
from .sensing.localization import MapAgreement, Confidence, planar_yaw


def yaw(q):
    return planar_yaw(q.x, q.y, q.z, q.w)


class LocalizationNode(Node):
    """Readiness for the legacy motor gate: AMCL tracking a pose D-395 confirmed.

    D-395 P2-3 (rejected alternative B): this node no longer publishes
    `initialpose` on a unique global match and no longer scatters AMCL with
    `reinitialize_global_localization`; on the 180-degree symmetric track both
    pick a mirror by chance. Candidates, injection and its 3 s check moved to
    `loc_assist_node`; "confirmed" here is its `localization/state` LOCALIZED.
    """

    def __init__(self):
        super().__init__('localization_monitor')
        for name, value in [('scan_timeout', .5), ('pose_timeout', 2.),
                            ('minimum_agreement', .85), ('wall_tolerance', .04),
                            ('position_stddev', .035), ('yaw_stddev', .12),
                            ('stable_scans', 10)]:
            self.declare_parameter(name, value)
        self.field = self.scan = self.pose = None
        self.confidence = Confidence(self.p('stable_scans'))
        self.tf = RobotTransformBuffer(self)
        self.listener = TransformListener(self.tf, self)
        self.status = self.create_publisher(String, 'localization/status', 10)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, 'map', self.on_map, latched)
        self.create_subscription(LaserScan, 'scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, 'amcl_pose', self.on_pose, latched)
        self.create_subscription(Bool, 'safety/pickup', self.on_pickup, 10)
        self.create_subscription(String, 'localization/state', self.on_state, latched)
        self.update_client = self.create_client(Empty, 'request_nomotion_update')
        self.last_update = -math.inf
        self.confirmed_at = None
        self.picked_up = False
        self.previous_time = None
        self.create_timer(.1, self.tick)

    def p(self, name):
        return self.get_parameter(name).value

    def on_map(self, msg):
        self.field = None
        self.confirmed_at = None
        self.confidence = Confidence(self.p('stable_scans'))
        try:
            rotation = yaw(msg.info.origin.orientation)
        except ValueError:
            return
        if (msg.header.frame_id != 'map' or not math.isfinite(msg.info.resolution) or msg.info.resolution <= 0 or
                msg.info.width <= 0 or msg.info.height <= 0 or
                not all(math.isfinite(v) for v in (msg.info.origin.position.x, msg.info.origin.position.y)) or
                msg.info.width * msg.info.height != len(msg.data) or
                abs(rotation) > 1e-6):
            return
        self.field = MapAgreement(np.array(msg.data).reshape(msg.info.height, msg.info.width),
                                  msg.info.resolution,
                                  (msg.info.origin.position.x, msg.info.origin.position.y),
                                  self.p('wall_tolerance'))

    def on_scan(self, msg):
        self.scan = msg

    def on_pose(self, msg):
        self.pose = msg

    def on_pickup(self, msg):
        self.picked_up = msg.data
        if msg.data:
            self.confirmed_at = None
            self.confidence = Confidence(self.p('stable_scans'))

    def on_state(self, msg):
        """D-395: only loc_assist's LOCALIZED (a decision that passed its 3 s check) confirms."""
        try:
            localized = json.loads(msg.data)['status']['state'] == 'LOCALIZED'
        except (TypeError, ValueError, KeyError):
            localized = False
        if not localized:
            self.confirmed_at = None
        elif self.confirmed_at is None:
            self.confirmed_at = self.get_clock().now().nanoseconds * 1e-9
            self.confidence = Confidence(self.p('stable_scans'))

    def scan_arrays(self):
        scan = self.scan
        ranges = np.asarray(scan.ranges)[::4]
        angles = scan.angle_min + np.arange(len(scan.ranges))[::4] * scan.angle_increment
        return np.where((ranges < scan.range_max) & (ranges >= scan.range_min), ranges, np.nan), angles

    def tick(self):
        now = self.get_clock().now().nanoseconds * 1e-9
        if self.previous_time is not None and now < self.previous_time:
            self.confirmed_at = None
        self.previous_time = now
        score = 0.
        reason = 'waiting-map-scan-pose'
        good = False
        stamp = 0
        fresh_scan = False
        if self.scan is not None:
            stamp = self.scan.header.stamp.sec * 1000000000 + self.scan.header.stamp.nanosec
            fresh_scan = 0 <= now - stamp * 1e-9 <= self.p('scan_timeout')
        if self.field is not None and fresh_scan and self.pose is not None:
            pose_t = self.pose.header.stamp.sec + self.pose.header.stamp.nanosec * 1e-9
            cov = self.pose.pose.covariance
            covariance_ok = all(math.isfinite(cov[i]) and 0 <= cov[i] <= limit**2
                                for i, limit in [(0, self.p('position_stddev')),
                                                 (7, self.p('position_stddev')),
                                                 (35, self.p('yaw_stddev'))])
            try:
                # Use the sensor frame at the observation time, including the
                # real rotated/offset lidar mount; never assume scan zero is nose.
                tf = self.tf.lookup_transform('map', self.scan.header.frame_id,
                                               rclpy.time.Time.from_msg(self.scan.header.stamp))
                tr, q = tf.transform.translation, tf.transform.rotation
                ranges, angles = self.scan_arrays()
                score = self.field.score((tr.x, tr.y, yaw(q)), ranges, angles)
                good = (self.confirmed_at is not None and not self.picked_up and covariance_ok and
                        0 <= now-pose_t <= self.p('pose_timeout') and pose_t > self.confirmed_at and
                        score >= self.p('minimum_agreement'))
                reason = 'tracking' if good else 'uncertain-or-map-mismatch'
                if self.confirmed_at is None:
                    reason = 'waiting-d395-localized'
            except Exception:
                reason = 'waiting-scan-transform'
        ready = self.confidence.observe(stamp, good)
        if not ready and good:
            reason = 'confirming'
        self.status.publish(String(data=json.dumps({'ready': ready, 'stamp_ns': stamp,
            'reason': reason, 'agreement': score})))
        # Stationary robots still have new lidar evidence. Do not repeatedly
        # reuse an old scan or invent movement to force particle updates.
        if fresh_scan and now-self.last_update >= .5 and self.update_client.service_is_ready():
            self.update_client.call_async(Empty.Request())
            self.last_update = now


def main():
    rclpy.init()
    node = LocalizationNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
