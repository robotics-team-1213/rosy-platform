"""Read-only robot worker for camera_auto; imports ROS only during capture."""
import json
import math
import os
from pathlib import Path
import time


class SampleClock:
    def __init__(self):
        self.stamps = {}

    def observe(self, name, stamp, now, max_age):
        if not math.isfinite(stamp) or stamp <= 0 or not -.05 <= now-stamp <= max_age:
            return 'stale_' + name
        if name in self.stamps and stamp <= self.stamps[name]:
            return 'repeated_' + name
        self.stamps[name] = stamp
        return None


class ScanGeometry:
    def __init__(self):
        self.geometry = None

    def observe(self, size, angle_min, increment, range_min, range_max):
        values = (angle_min, increment, range_min, range_max)
        if (size < 2 or not all(math.isfinite(v) for v in values)
                or abs(increment) <= 1e-12 or range_min < 0 or range_max <= range_min):
            return 'invalid_scan_geometry'
        geometry = (size, *values)
        if self.geometry is not None and geometry != self.geometry:
            return 'scan_geometry_changed'
        self.geometry = geometry
        return None


class StationaryCapture:
    def __init__(self):
        self.initial = None
        self.last_odom = None
        self.errors = set()

    def observe_odom(self, x, y, yaw, speed, angular, now):
        if not all(math.isfinite(v) for v in (x, y, yaw, speed, angular, now)):
            self.errors.add('invalid_odometry')
            return
        self.last_odom = now
        if self.initial is None:
            self.initial = (x, y, yaw)
        if abs(speed) > .005 or abs(angular) > math.radians(1):
            self.errors.add('moving')
        delta = yaw - self.initial[2]
        if (math.hypot(x-self.initial[0], y-self.initial[1]) > .005
                or abs(math.atan2(math.sin(delta), math.cos(delta))) > math.radians(1)):
            self.errors.add('drift')

    def faults(self, now):
        result = set(self.errors)
        if self.last_odom is None or not 0 <= now-self.last_odom <= .25:
            result.add('stale_odometry')
        return sorted(result)


def capture():
    for line in Path('/etc/rosy/runtime.env').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in ('ROS_DOMAIN_ID', 'RMW_IMPLEMENTATION', 'CYCLONEDDS_URI', 'ROS_LOCALHOST_ONLY'):
                os.environ[key] = value.strip('"')
    import numpy as np
    import yaml
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, LaserScan
    from nav_msgs.msg import Odometry
    from control.calibration_camera import run_camera_extrinsic

    share = Path('/opt/rosy/current/install/share/pinky_pro/config')
    geometry = yaml.safe_load((share/'geometry.yaml').read_text())
    lidar = geometry['lidar']
    rclpy.init()
    node = rclpy.create_node('camera_autocalib_readonly_' + str(os.getpid()))
    guard = StationaryCapture()
    clock = SampleClock()
    scan_geometry = ScanGeometry()
    scans, frames, subscriptions = [], [], []
    fresh = {}
    errors = set()
    odom_count = 0

    def sample(name, msg, max_age):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec/1e9
        error = clock.observe(name, stamp, node.get_clock().now().nanoseconds/1e9, max_age)
        if error:
            errors.add(error)
            return False
        fresh[name] = time.monotonic()
        return True

    def camera(msg):
        if not sample('camera', msg, .5):
            return
        if msg.encoding not in ('bgr8', 'rgb8'):
            errors.add('unsupported_image')
            return
        if len(frames) < 15:
            try:
                rows = np.frombuffer(bytes(msg.data), np.uint8).reshape(msg.height, msg.step)
                frame = rows[:, :msg.width*3].reshape(msg.height, msg.width, 3).mean(axis=2, dtype=np.float32)
                if frames and frame.shape != frames[0].shape:
                    errors.add('camera_shape_changed')
                else:
                    frames.append(frame)
            except ValueError:
                errors.add('invalid_image')

    def scan(msg):
        if not sample('scan', msg, .5):
            return
        error = scan_geometry.observe(len(msg.ranges), msg.angle_min, msg.angle_increment,
                                      msg.range_min, msg.range_max)
        if error:
            errors.add(error)
            return
        if len(scans) < 40:
            if scans and len(scans[0][0]) != len(msg.ranges):
                errors.add('scan_shape_changed')
            else:
                scans.append((list(msg.ranges), msg.angle_min, msg.angle_increment, msg.range_min, msg.range_max))

    def odom(msg):
        nonlocal odom_count
        if not sample('odom', msg, .25):
            return
        odom_count += 1
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        quaternion = (q.x, q.y, q.z, q.w)
        if (not all(math.isfinite(v) for v in quaternion)
                or abs(sum(v*v for v in quaternion)-1) > .01):
            errors.add('invalid_odometry_quaternion')
            return
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        v, w = msg.twist.twist.linear, msg.twist.twist.angular
        guard.observe_odom(p.x, p.y, yaw, math.hypot(v.x, v.y), w.z, time.monotonic())

    try:
        start = time.monotonic()
        while time.monotonic()-start < 3:
            rclpy.spin_once(node, timeout_sec=.1)
        topics = node.get_topic_names_and_types()
        for suffix, cls, callback in [('camera/front', Image, camera), ('scan', LaserScan, scan), ('odom', Odometry, odom)]:
            names = [n for n, _ in topics if n.endswith('/'+suffix) or n == '/'+suffix]
            if len(names) != 1:
                errors.add('topic_not_unique:' + suffix)
            else:
                subscriptions.append(node.create_subscription(cls, names[0], callback, qos_profile_sensor_data))
        start = time.monotonic()
        while time.monotonic()-start < 4:
            rclpy.spin_once(node, timeout_sec=.05)
            now = time.monotonic()
            if now-start > 1:
                errors.update(guard.faults(now))
                for name in ('scan', 'camera'):
                    if name not in fresh or now-fresh[name] > .5:
                        errors.add('stale_' + name)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    result = {'robot_id': os.uname().nodename, 'scans': len(scans), 'frames': len(frames),
              'odom': odom_count, 'faults': sorted(errors), 'motion_command_published': False,
              'lidar_mount_source': 'URDF_NOMINAL_NOT_MEASURED'}
    if errors or len(scans) < 10 or len(frames) < 5:
        result['fit'] = {'error': 'stationary sensor prerequisite failed'}
    else:
        result['fit'] = run_camera_extrinsic(
            scans=scans, frames=frames, yaw_offset_rad=lidar['yaw_rad'],
            lidar_x_m=lidar['x_m'], tf_nose_rad=lidar['yaw_rad'],
            profile_path=str(share/'camera_nominal.yaml'))
    return result


if __name__ == '__main__':
    print(json.dumps(capture(), allow_nan=False))
