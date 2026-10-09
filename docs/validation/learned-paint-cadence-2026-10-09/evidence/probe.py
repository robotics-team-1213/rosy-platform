"""Read-only live reproduction of the installed learned paint worker cadence."""

import argparse
import json
import statistics
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

from control.sensing.perception.image_frame import image_msg_to_frame
from control.sensing.perception.learned.paint_worker import LearnedPaintWorker
from control.sensing.perception.learned.runner import LaneSegModel, ModelSlot
from control.sensing.perception.lane_bev import pose_if_fresh


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--namespace", required=True)
parser.add_argument("--pointer", required=True)
parser.add_argument("--threads", type=int, required=True)
parser.add_argument("--frames", type=int, default=50)
args = parser.parse_args()
if not args.namespace.startswith("/") or args.threads < 1 or args.frames < 2:
    parser.error("namespace must be absolute; threads >= 1; frames >= 2")

slot = ModelSlot(args.pointer, opener=lambda path: LaneSegModel.open(
    path, threads=args.threads, allow_spinning=False))
model = slot.poll()
if model is None:
    raise RuntimeError(f"installed model did not load: {slot.last_error}")
worker = LearnedPaintWorker(slot)
result = dict(frames=0, learned=0, fallback=0, effective_every_n_1=0,
              fresh_odom=0, model_revision=model.model_revision)
stamps = []
odom = [None, None]
rclpy.init()
node = rclpy.create_node("lane_paint_cadence_probe_readonly")


def on_odom(msg):
    odom[0] = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
    odom[1] = float(msg.twist.twist.angular.z)


def on_image(msg):
    if result["frames"] >= args.frames:
        return
    stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
    wz = pose_if_fresh(odom[1], odom[0], stamp)
    if wz is not None:
        result["fresh_odom"] += 1
    every_n = 1 if wz is None or abs(wz) > 0.15 else 2
    result["effective_every_n_1"] += every_n == 1
    mask = worker.mask_for(image_msg_to_frame(msg), every_n, stamp)
    result["learned" if mask is not None else "fallback"] += 1
    result["frames"] += 1
    stamps.append(stamp)


node.create_subscription(Odometry, args.namespace + "/odom", on_odom, qos_profile_sensor_data)
node.create_subscription(Image, args.namespace + "/camera/front", on_image, qos_profile_sensor_data)
deadline = time.monotonic() + 15
while result["frames"] < args.frames and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.25)
result["last_error"] = worker.last_error
result["frame_period_median_ms"] = round(1000 * statistics.median(
    b - a for a, b in zip(stamps, stamps[1:])), 1) if len(stamps) > 1 else None
result["last_result_latency_ms"] = worker._result[2]["latency_ms"] if worker._result else None
worker.close()
node.destroy_node()
rclpy.shutdown()
assert result["learned"] + result["fallback"] == result["frames"]
print(json.dumps(result, sort_keys=True))
