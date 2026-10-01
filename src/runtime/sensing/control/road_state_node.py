#!/usr/bin/env python3
"""road_state_node — D-384 road-state estimator in shadow (R1).

R1 needs line_observer_node in keep mode (camera_lane_mode: keep): only that
mode publishes line/keep_debug, the LaneKeeper bundle this node estimates
from. In any other lane mode this node receives no boundaries and stays STOP.
IR evidence is OFF until the IR bar spacing is measured
(ir_geometry_measured; ir_half_span_m 0.020 is the URDF nominal, D-397).

Subscribes:
  odom                        nav_msgs/Odometry; pose deltas drive the prediction
                              (a dropped sample loses no travel)
  line/keep_debug             LaneKeeper.last per camera frame (keep mode only;
                              line_observer publishes it there). Uses
                              last['candidates'] when the lane owner adds it,
                              else last['boundaries'].
  line/observation            IR_LINE samples -> IrMeas (CAMERA_LINE ignored)
  perception/learned/shadow   learned offset (D-356), latency compensated
  scan                        only with lidar_wall_veto (off by default until
                              the LiDAR yaw calibration lands)
Publishes perception/road_state (std_msgs/String JSON, RELIABLE, depth 1,
TRANSIENT_LOCAL) once per keep_debug frame: the estimator snapshot plus the
R1 log fields (image stamp, ground profile/pitch, raw odom pose/twist, the
keeper's candidate list, SW revision). Observation only: this node never
publishes or logs a command, and nothing in the control path reads it (D-369).
"""

import json
import math
import os

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from . import executor_choice
from .sensing.perception.road_state import (
    TOPIC,
    IrMeas,
    OdomBuffer,
    RoadStateEstimator,
    RoadStateParams,
    boundaries_from_keep,
    decision_point_from_keep,
    offset_from_shadow,
    wall_segments_from_scan,
)


def _stamp(header) -> float:
    return float(header.stamp.sec) + float(header.stamp.nanosec) * 1e-9


def _yaw(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def _load(text):
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


class RoadStateNode(Node):
    def __init__(self):
        super().__init__('road_state_node')
        self.declare_parameter('lane_width_m', 0.185)
        # R1 log context: the ground profile the keeper ran on and its pitch.
        self.declare_parameter('ground_profile_id', '')
        self.declare_parameter('camera_pitch_deg', 0.0)
        # IR bar: lateral offset of an outer sensor from the centre one.
        # URDF nominal (D-397 geometry.yaml ir.half_span_m), not measured on the robot.
        self.declare_parameter('ir_half_span_m', 0.020)
        self.declare_parameter('ir_geometry_measured', False)
        self.declare_parameter('ir_calibrated', False)
        self.declare_parameter('ir_max_age_s', 0.2)
        self.declare_parameter('lidar_wall_veto', False)
        self.declare_parameter('lidar_yaw_offset_deg', 180.0)
        self.declare_parameter('route_hint', '')
        self.declare_parameter('sw_revision', os.environ.get('ROSY_SW_REVISION', ''))
        width = float(self.get_parameter('lane_width_m').value)
        veto = bool(self.get_parameter('lidar_wall_veto').value)
        hint = str(self.get_parameter('route_hint').value) or None
        self._ir_on = bool(self.get_parameter('ir_geometry_measured').value)
        self._est = RoadStateEstimator(RoadStateParams(
            lane_width_m=width, lidar_wall_veto=veto, mode='shadow', ir_geometry_measured=self._ir_on,
            ir_calibrated=bool(self.get_parameter('ir_calibrated').value)), route_hint=hint)
        self._half = width / 2.0
        self._odom = None       # (stamp, x, y, yaw, v, w), the latest, for the R1 log
        self._odom_buffer = OdomBuffer()
        self._ir = None         # (stamp, y)
        self._learned = None    # payload not yet used
        self._walls = []
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        latest = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self._pub = self.create_publisher(String, TOPIC, latched)
        self.create_subscription(Odometry, 'odom', self._on_odom, latest)
        self.create_subscription(String, 'line/keep_debug', self._on_keep, latest)
        # IR_LINE and CAMERA_LINE share this topic: a short queue keeps an IR
        # sample from being overwritten by the camera sample right after it.
        self.create_subscription(String, 'line/observation', self._on_line,
                                 QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(String, 'perception/learned/shadow', self._on_learned, latest)
        if veto:
            self.create_subscription(LaserScan, 'scan', self._on_scan, latest)

    def _on_odom(self, msg: Odometry) -> None:
        stamp = _stamp(msg.header)
        pose = msg.pose.pose
        x, y, yaw = float(pose.position.x), float(pose.position.y), _yaw(pose.orientation)
        twist = msg.twist.twist
        self._odom = (stamp, x, y, yaw, float(twist.linear.x), float(twist.angular.z))
        # Held until a camera frame: the estimator is advanced to the image stamp,
        # never past it, so its clock never runs backwards.
        self._odom_buffer.add(stamp, x, y, yaw)

    def _on_line(self, msg: String) -> None:
        doc = _load(msg.data)
        if doc is None or doc.get('source') != 'IR_LINE':
            return
        error, stamp = doc.get('error'), doc.get('stamp')
        if not doc.get('visible') or not isinstance(error, (int, float)) \
                or not isinstance(stamp, (int, float)):
            self._ir = None
            return
        # Left tape decodes negative (ir_calibration): base_link y is left +.
        self._ir = (float(stamp), -float(error) * float(self.get_parameter('ir_half_span_m').value))

    def _on_learned(self, msg: String) -> None:
        self._learned = _load(msg.data)

    def _on_scan(self, msg: LaserScan) -> None:
        self._walls = wall_segments_from_scan(
            msg.ranges, float(msg.angle_min), float(msg.angle_increment),
            yaw_offset_rad=math.radians(float(self.get_parameter('lidar_yaw_offset_deg').value)))

    def _on_keep(self, msg: String) -> None:
        bundle = _load(msg.data)
        if bundle is None:
            return
        stamp = bundle.get('stamp')
        if not isinstance(stamp, (int, float)):
            return
        stamp = float(stamp)
        for ds, dtheta, dt, odom_stamp in self._odom_buffer.advance_to(stamp):
            self._est.predict(ds, dtheta, dt=dt, stamp=odom_stamp)
        records = bundle.get('candidates')
        source = 'candidates' if records is not None else 'boundaries'
        measurements = boundaries_from_keep(bundle)
        ir = None
        if self._ir_on and self._ir is not None and abs(stamp - self._ir[0]) <= float(
                self.get_parameter('ir_max_age_s').value):
            ir = self._ir[1]
            measurements.append(IrMeas(y=ir))
        learned = offset_from_shadow(self._learned or {}, half_width_m=self._half)
        self._learned = None     # each learned sample is used once
        if learned is not None:
            measurements.append(learned)
        measurements.extend(self._walls)
        profile = str(self.get_parameter('ground_profile_id').value) or bundle.get('ground')
        self._est.update(measurements, stamp, profile=profile,
                         decision_point=decision_point_from_keep(bundle))
        snapshot = self._est.snapshot()
        odom = self._odom
        snapshot.update({
            'image_stamp': stamp,
            'ground': {'profile': profile,
                       'pitch_deg': float(self.get_parameter('camera_pitch_deg').value)},
            'odom': None if odom is None else {
                'stamp': odom[0], 'pose': {'x': odom[1], 'y': odom[2], 'yaw': odom[3]},
                'twist': {'v': odom[4], 'w': odom[5]}},
            'keeper': {'strategy': bundle.get('strategy'), 'reason': bundle.get('reason'),
                       'candidates_source': source,
                       'candidates': [{k: v for k, v in r.items() if k not in ('ends_px', 'pursuit_m')}
                                      for r in (records if records is not None
                                                else bundle.get('boundaries') or [])
                                      if isinstance(r, dict)]},
            'inputs': {'ir_y_m': ir,
                       'learned': None if learned is None else {
                           'd': learned.d, 'sigma': learned.sigma, 'stamp': learned.stamp,
                           'wall_fraction': learned.wall_fraction}},
            'sw_revision': str(self.get_parameter('sw_revision').value) or None,
        })
        self._pub.publish(String(data=json.dumps(snapshot, sort_keys=True, default=float)))


def main():
    rclpy.init()
    node = RoadStateNode()
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
