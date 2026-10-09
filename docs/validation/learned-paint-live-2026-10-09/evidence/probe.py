"""Read live keep-debug provenance and time the installed model; never publish ROS messages."""

import argparse
import collections
import json
import math
import statistics
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

from control.sensing.perception.image_frame import image_msg_to_frame
from control.sensing.perception.learned.runner import LaneSegModel, ModelSlot


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--namespace", required=True)
parser.add_argument("--pointer", required=True)
parser.add_argument("--threads", required=True, type=int)
args = parser.parse_args()
if args.threads < 1 or not args.namespace.startswith("/"):
    parser.error("threads must be positive and namespace must be absolute")

debug, images = [], []
rclpy.init()
node = rclpy.create_node("lane_paint_probe_readonly")
node.create_subscription(String, args.namespace + "/line/keep_debug",
                         lambda msg: debug.append(json.loads(msg.data)), 10)
node.create_subscription(Image, args.namespace + "/camera/front",
                         lambda msg: images.append(image_msg_to_frame(msg)) if not images else None,
                         qos_profile_sensor_data)
deadline = time.monotonic() + 6
while len(debug) < 25 and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.5)
node.destroy_node()
rclpy.shutdown()

sources = collections.Counter(row.get("paint_source_used") for row in debug)
projection = [row.get("ground_projection") for row in debug]
result = {"frames": len(debug), "paint_source_used": dict(sources),
          "paint_model_revisions_used": sorted({row["paint_model_revision"] for row in debug
                                                 if row.get("paint_model_revision")}),
          "ground_projections_present": sum(isinstance(p, dict) for p in projection),
          "image_stamps_present": sum(isinstance(row.get("stamp"), (int, float))
                                       for row in debug), "camera_frame_received": bool(images)}
if images:
    slot = ModelSlot(args.pointer, opener=lambda path: LaneSegModel.open(
        path, threads=args.threads, allow_spinning=False))
    model = slot.poll()
    result["model_loaded"] = model is not None
    result["model_error"] = slot.last_error
    if model is not None:
        timings = []
        for _ in range(3):
            mask, elapsed = model.infer_mask(images[0])
            assert mask.shape == images[0].shape[:2] and math.isfinite(elapsed) and elapsed >= 0
            timings.append(round(elapsed, 1))
        result.update(model_revision=model.model_revision, inference_ms=timings,
                      inference_median_ms=round(statistics.median(timings), 1))
print(json.dumps(result, sort_keys=True))
