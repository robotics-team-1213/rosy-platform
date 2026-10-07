#!/usr/bin/env python3
"""B8 SIM recorder (model PC only): camera frames + keeper bundle + ground truth.

Runs beside the D-495 harness (same ROS_DOMAIN_ID). Per camera/front frame it keeps the raw
image, the latest d495/gt pose and the last /cmd_vel; every line/keep_debug bundle is kept
as-is (its 'stamp' is the image header stamp, so frames and bundles join on stamp).

  python3 b8_record.py --out runs/<name> --duration 90

Writes <out>/frames.npz (frames uint8 N x H x W x 3, stamp, gt N x 3, cmd N x 2, compressed)
and <out>/keep.jsonl. Stops after --duration wall seconds or on SIGINT/SIGTERM.
"""
import argparse
import json
import os
import signal
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--duration', type=float, default=90.0)
    a = ap.parse_args()
    import numpy as np
    import rclpy
    from geometry_msgs.msg import Pose2D, Twist
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from std_msgs.msg import String

    os.makedirs(a.out, exist_ok=True)
    rclpy.init()
    n = rclpy.create_node('b8_record')
    st = {'gt': (float('nan'),) * 3, 'cmd': (0.0, 0.0)}
    frames, stamps, gts, cmds = [], [], [], []
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

    n.create_subscription(Image, 'camera/front', on_image, qos_profile_sensor_data)
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
                        gt=np.asarray(gts, float), cmd=np.asarray(cmds, float))
    print('frames', len(frames))


if __name__ == '__main__':
    main()
