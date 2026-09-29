"""Teleport the robot along lane_graph segments and save camera frames."""
import math
import os
import subprocess
import sys
import time

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from sensor_msgs.msg import Image

OUT = sys.argv[1]
GRAPH = sys.argv[2]
COUNT = int(sys.argv[3]) if len(sys.argv) > 3 else 20
TAG = sys.argv[4] if len(sys.argv) > 4 else "sim"
os.makedirs(OUT, exist_ok=True)

graph = yaml.safe_load(open(GRAPH))
poses = []
for name in ("west", "east"):
    pts = graph["segments"][name]["points"]
    step = max(1, len(pts) // (COUNT // 2))
    for i in range(0, len(pts) - 3, step):
        (x0, y0), (x1, y1) = pts[i], pts[i + 3]
        poses.append((name, x0, y0, math.atan2(y1 - y0, x1 - x0)))
poses = poses[:COUNT]

rclpy.init()
node = Node("real_profile_grab")
latest = {}


def cb(m):
    ch = 3 if m.encoding in ("rgb8", "bgr8") else 1
    a = np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, ch).copy()
    if m.encoding == "rgb8":
        a = a[:, :, ::-1]
    latest["img"] = a
    latest["t"] = time.time()


node.create_subscription(Image, "camera/front", cb, 1)


def spin_for(sec):
    end = time.time() + sec
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.1)


spin_for(3.0)
if "img" not in latest:
    spin_for(20.0)
print("first frame", "img" in latest, flush=True)

for k, (name, x, y, yaw) in enumerate(poses):
    qz, qw = math.sin(yaw / 2), math.cos(yaw / 2)
    req = (f'name: "rosy", position: {{x: {x}, y: {y}, z: 0.002}}, '
           f'orientation: {{x: 0, y: 0, z: {qz}, w: {qw}}}')
    r = subprocess.run(
        ["gz", "service", "-s", "/world/map_v2_fleet/set_pose", "--reqtype", "gz.msgs.Pose",
         "--reptype", "gz.msgs.Boolean", "--timeout", "3000", "--req", req],
        capture_output=True, text=True)
    t0 = time.time()
    spin_for(2.5)
    if latest.get("t", 0) > t0 + 1.0:
        path = f"{OUT}/{TAG}_{k:02d}_{name}.png"
        cv2.imwrite(path, latest["img"])
        g = cv2.cvtColor(latest["img"], cv2.COLOR_BGR2GRAY)
        print(k, name, round(x, 3), round(y, 3), round(math.degrees(yaw), 1),
              r.stdout.strip(), "mean", round(float(g.mean()), 1),
              "bottom", round(float(g[200:].mean()), 1), flush=True)
    else:
        print(k, "no fresh frame", r.stdout.strip(), r.stderr.strip()[:200], flush=True)
node.destroy_node()
rclpy.shutdown()
