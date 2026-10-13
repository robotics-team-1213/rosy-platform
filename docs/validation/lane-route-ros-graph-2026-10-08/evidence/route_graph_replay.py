#!/usr/bin/env python3
"""Feed recorded Gazebo image/odom into an isolated line observer ROS graph."""
import argparse
import json
import math
import time

import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image
from std_msgs.msg import String


def stamp_message(message, stamp):
    sec = int(stamp)
    message.header.stamp.sec = sec
    message.header.stamp.nanosec = round((stamp - sec) * 1_000_000_000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("frames")
    parser.add_argument("output")
    args = parser.parse_args()
    frames = np.load(args.frames)
    rclpy.init()
    node = rclpy.create_node("route_graph_replay")
    images = node.create_publisher(Image, "camera/front", qos_profile_sensor_data)
    odom = node.create_publisher(Odometry, "odom", qos_profile_sensor_data)
    clock = node.create_publisher(Clock, "/clock", 10)
    received = {}

    def on_observation(message):
        payload = json.loads(message.data)
        if payload.get("source") == "CAMERA_LINE":
            received[round(payload["stamp"], 6)] = payload

    node.create_subscription(String, "line/observation", on_observation, 10)
    deadline = time.monotonic() + 15
    while (images.get_subscription_count() < 1 or odom.get_subscription_count() < 1
           or clock.get_subscription_count() < 1):
        if time.monotonic() > deadline:
            raise RuntimeError("line observer did not subscribe")
        rclpy.spin_once(node, timeout_sec=0.1)

    sent = []
    for index in range(76, 201):
        t = float(frames["stamp"][index])
        sec = int(t)
        tick = Clock()
        tick.clock.sec = sec
        tick.clock.nanosec = round((t - sec) * 1_000_000_000)
        clock.publish(tick)
        position = frames["gt"][index]
        pose = Odometry()
        stamp_message(pose, t)
        pose.header.frame_id = "odom"
        pose.child_frame_id = "base_link"
        pose.pose.pose.position.x = float(position[0])
        pose.pose.pose.position.y = float(position[1])
        pose.pose.pose.orientation.z = math.sin(float(position[2]) / 2)
        pose.pose.pose.orientation.w = math.cos(float(position[2]) / 2)
        odom.publish(pose)
        rclpy.spin_once(node, timeout_sec=0.03)
        data = frames["frames"][index]
        image = Image()
        stamp_message(image, t)
        image.header.frame_id = "camera_front"
        image.height, image.width = data.shape[:2]
        image.encoding = "bgr8"
        image.step = image.width * 3
        image.data = data.tobytes()
        images.publish(image)
        key = round(t, 6)
        until = time.monotonic() + 1.5
        while key not in received and time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.05)
        sent.append((index, key))
    result = {
        "sent": len(sent),
        "received": sum(key in received for _, key in sent),
        "missing_indices": [index for index, key in sent if key not in received],
        "bend": {str(index): received.get(key) for index, key in sent if 188 <= index <= 200},
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
