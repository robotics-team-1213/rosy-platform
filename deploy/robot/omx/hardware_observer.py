#!/usr/bin/env python3
"""Bounded, read-only physical feedback for commissioning; never a motion owner."""
import argparse
import json
import math
import os
import time

JOINTS = ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]
TOPIC = "/omx_commissioning/joint_states"


def positions(rows, elapsed):
    if not math.isfinite(elapsed) or not 0 <= elapsed <= .25:
        raise ValueError("Register snapshot exceeded the 250 ms freshness bound")
    if [row["id"] for row in rows] != list(range(11, 17)):
        raise ValueError("Expected exactly the six ordered follower motors")
    for row in rows:
        expected = 1060 if row["id"] < 14 else 1200
        if (row["model_number"] != expected or row["torque_enabled"] != 0
                or row["hardware_error"] != 0):
            raise ValueError("Model mismatch, torque enabled or motor fault")
    # Present Position already contains Homing Offset; mirror the pinned vendor units.
    return [row["position_raw"] * math.tau / 4096 - math.pi for row in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--domain-id", type=int, required=True)
    parser.add_argument("--duration", type=float, required=True, help="bounded observation, 1..300 seconds")
    args = parser.parse_args(argv)
    if not 0 <= args.domain_id <= 232 or not math.isfinite(args.duration) or not 1 <= args.duration <= 300:
        parser.error("domain-id must be 0..232 and duration 1..300 seconds")
    os.environ["ROS_AUTOMATIC_DISCOVERY_RANGE"] = "LOCALHOST"
    from register_probe import open_readonly_port, read_motors
    import rclpy
    from sensor_msgs.msg import JointState

    node = None
    count = 0
    result = 2
    try:
        rclpy.init(domain_id=args.domain_id)
        node = rclpy.create_node("rosy_omx_readonly_observer")
        publisher = node.create_publisher(JointState, TOPIC, 1)
        deadline = time.monotonic() + args.duration
        with open_readonly_port(args.device) as port:
            while rclpy.ok() and time.monotonic() < deadline:
                started = time.monotonic()
                stamp = node.get_clock().now().to_msg()
                rows = read_motors(port)
                message = JointState()
                message.header.stamp = stamp
                message.name = JOINTS
                message.position = positions(rows, time.monotonic() - started)
                publisher.publish(message)
                count += 1
                print(json.dumps({"sample": count, "captured_at": time.time(),
                                  "motors": rows, "motion_admitted": False}), flush=True)
                time.sleep(max(0, .1 - (time.monotonic() - started)))
        result = 0 if count else 2
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"error": str(error), "motion_admitted": False}), flush=True)
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        print(json.dumps({"samples": count, "exit_code": result, "motion_admitted": False}), flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
