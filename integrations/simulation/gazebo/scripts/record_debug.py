#!/usr/bin/env python3
"""Record line/debug/compressed to <out>/overlay.mp4 plus frames.jsonl.

Usage: ros2 run gz_sim record_debug.py --out DIR [--seconds 180] [--fps 5]
Observation only; subscribes, never publishes.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--topic", default="line/debug/compressed")
    args, ros_args = parser.parse_known_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    rclpy.init(args=ros_args)
    node = Node("lane_debug_recorder")
    state = {"writer": None, "count": 0}
    log = (args.out / "frames.jsonl").open("w", encoding="utf-8")

    def on_image(msg):
        image = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return
        if state["writer"] is None:
            path = args.out / "overlay.mp4"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), args.fps,
                (image.shape[1], image.shape[0]))
            if not writer.isOpened():
                raise RuntimeError(f"could not open a video writer for {path}")
            state["writer"] = writer
        state["writer"].write(image)
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        log.write(json.dumps({"index": state["count"], "stamp": stamp}) + "\n")
        log.flush()
        state["count"] += 1

    node.create_subscription(CompressedImage, args.topic, on_image, qos_profile_sensor_data)
    deadline = time.monotonic() + args.seconds
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if state["writer"] is not None:
            state["writer"].release()
        log.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    print(f"recorded {state['count']} frames to {args.out / 'overlay.mp4'}")
    return 0 if state["count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
