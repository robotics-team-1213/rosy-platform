#!/usr/bin/env python3
"""Lap SIM recorder (model PC only): lane-ws-corner-sim-2026-10-08 ws_record.py unchanged (B8 b8_record.py plus odometry).

Same as docs/validation/lane-trip-perception-2026-10-07/evidence/b8_record.py (raw camera/front
frames, d495/gt, last /cmd_vel, every line/keep_debug bundle) and, per frame, the latest odom
(x, y, yaw, vx, wz, header stamp) the line observer sees, so an offline replay can apply the
node's keeper restarts (camera gap or spin in place) exactly.

  python3 lap_record.py --out runs/<name>/rec --duration 120
"""
import argparse
import math
import os
import signal
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--duration', type=float, default=120.0)
    a = ap.parse_args()
    import numpy as np
    import rclpy
    from geometry_msgs.msg import Pose2D, Twist
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from std_msgs.msg import String

    os.makedirs(a.out, exist_ok=True)
    rclpy.init()
    n = rclpy.create_node('lap_record')
    nan = float('nan')
    st = {'gt': (nan,) * 3, 'cmd': (0.0, 0.0), 'odom': (nan,) * 6}
    frames, stamps, gts, cmds, odoms = [], [], [], [], []
    keep = open(os.path.join(a.out, 'keep.jsonl'), 'w')

    def on_image(m):
        if m.encoding not in ('rgb8', 'bgr8'):
            return
        img = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.step)[:, :m.width * 3]
        img = img.reshape(m.height, m.width, 3)
        frames.append(img[:, :, ::-1].copy() if m.encoding == 'rgb8' else img.copy())  # BGR
        stamps.append(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)
        gts.append(st['gt'])
        cmds.append(st['cmd'])
        odoms.append(st['odom'])

    def on_odom(m):
        q = m.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        st['odom'] = (m.pose.pose.position.x, m.pose.pose.position.y, yaw,
                      m.twist.twist.linear.x, m.twist.twist.angular.z,
                      m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)

    n.create_subscription(Image, 'camera/front', on_image, qos_profile_sensor_data)
    n.create_subscription(Odometry, 'odom', on_odom, qos_profile_sensor_data)
    n.create_subscription(String, 'line/keep_debug', lambda m: keep.write(m.data + '\n'), 50)
    n.create_subscription(Pose2D, 'd495/gt', lambda m: st.__setitem__('gt', (m.x, m.y, m.theta)), 10)
    n.create_subscription(Twist, 'cmd_vel', lambda m: st.__setitem__('cmd', (m.linear.x, m.angular.z)), 10)
    stop = [False]
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    end = time.time() + a.duration
    while not stop[0] and time.time() < end:
        rclpy.spin_once(n, timeout_sec=0.1)
    keep.close()
    np.savez_compressed(os.path.join(a.out, 'frames.npz'),
                        frames=np.asarray(frames, np.uint8), stamp=np.asarray(stamps),
                        gt=np.asarray(gts, float), cmd=np.asarray(cmds, float),
                        odom=np.asarray(odoms, float))
    print('frames', len(frames))


if __name__ == '__main__':
    main()
