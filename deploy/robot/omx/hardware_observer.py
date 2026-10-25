#!/usr/bin/env python3
"""Bounded, read-only physical feedback for commissioning; never a motion owner."""
import argparse
import json
import math
import os
import re
import time

JOINTS = ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]
TOPIC = "/omx_commissioning/joint_states"


def joint_topic(value):
    if value != TOPIC and not re.fullmatch(r"/omx_commissioning/[A-Za-z_][A-Za-z0-9_]*/joint_states", value):
        raise ValueError("joint topic must stay in the OMX commissioning namespace")
    return value


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
    lifetime = parser.add_mutually_exclusive_group(required=True)
    lifetime.add_argument("--duration", type=float, help="bounded observation, 1..300 seconds")
    lifetime.add_argument("--persistent", action="store_true", help="explicit torque-OFF observation until stopped")
    parser.add_argument("--joint-topic", type=joint_topic, default=TOPIC)
    parser.add_argument('--health-file', help='explicit atomic health snapshot path, no additional serial reader')
    parser.add_argument('--health-owner', help='registered workcell arm identity')
    args = parser.parse_args(argv)
    if bool(args.health_file) != bool(args.health_owner):
        parser.error('health-file and health-owner must be configured together')
    if (not 0 <= args.domain_id <= 232 or (not args.persistent and
            (not math.isfinite(args.duration) or not 1 <= args.duration <= 300))):
        parser.error("domain-id must be 0..232 and duration 1..300 seconds")
    for key in ("CYCLONEDDS_URI", "FASTDDS_DEFAULT_PROFILES_FILE",
                "FASTRTPS_DEFAULT_PROFILES_FILE", "ROS_DISCOVERY_SERVER"):
        if os.environ.get(key):
            parser.error(f"External discovery override is not allowed: {key}")
    if os.environ.get("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp") != "rmw_fastrtps_cpp":
        parser.error("This commissioning observer is validated only with rmw_fastrtps_cpp")
    os.environ["RMW_IMPLEMENTATION"] = "rmw_fastrtps_cpp"
    os.environ["ROS_STATIC_PEERS"] = ""
    os.environ["ROS_AUTOMATIC_DISCOVERY_RANGE"] = "LOCALHOST"
    from register_probe import open_readonly_port, read_motors
    import rclpy
    from sensor_msgs.msg import JointState

    node = None
    count = 0
    result = 2
    health, failure = None, None
    if args.health_file:
        from passive_motor_health import PassiveMotorHealth
        health = PassiveMotorHealth(args.health_file, args.health_owner)
    try:
        rclpy.init(domain_id=args.domain_id)
        suffix = "" if args.joint_topic == TOPIC else "_" + args.joint_topic.split("/")[2]
        node = rclpy.create_node("rosy_omx_readonly_observer" + suffix)
        publisher = node.create_publisher(JointState, args.joint_topic, 1)
        print(json.dumps({"event": "observer_start", "device": args.device,
                          "joint_topic": args.joint_topic, "persistent": args.persistent,
                          "motion_admitted": False}), flush=True)
        deadline = None if args.persistent else time.monotonic() + args.duration
        with open_readonly_port(args.device) as port:
            while rclpy.ok() and (deadline is None or time.monotonic() < deadline):
                started = time.monotonic()
                captured_at = time.time()
                stamp = node.get_clock().now().to_msg()
                rows = read_motors(port, allow_fault=True) if health is not None else read_motors(port)
                if health is not None:
                    health.sample(rows, captured_at=captured_at, elapsed=time.monotonic() - started)
                message = JointState()
                message.header.stamp = stamp
                message.name = JOINTS
                message.position = positions(rows, time.monotonic() - started)
                publisher.publish(message)
                count += 1
                print(json.dumps({"sample": count, "captured_at": time.time(),
                                  "device": args.device, "joint_topic": args.joint_topic,
                                  "motors": rows, "motion_admitted": False}), flush=True)
                time.sleep(max(0, .1 - (time.monotonic() - started)))
        result = 0 if count and (deadline is None or time.monotonic() >= deadline) else 2
    except (Exception, KeyboardInterrupt) as error:
        failure = error
        print(json.dumps({"error": str(error), "motion_admitted": False}), flush=True)
    finally:
        if health is not None:
            try:
                health.end(failure)
            except Exception as error:
                result = 2
                print(json.dumps({'health_cleanup_error': type(error).__name__, 'motion_admitted': False}), flush=True)
        try:
            if node is not None:
                node.destroy_node()
        except Exception as error:
            result = 2
            print(json.dumps({"cleanup_error": str(error), "motion_admitted": False}), flush=True)
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception as error:
            result = 2
            print(json.dumps({"cleanup_error": str(error), "motion_admitted": False}), flush=True)
        print(json.dumps({"samples": count, "exit_code": result, "motion_admitted": False,
                          "device": args.device, "joint_topic": args.joint_topic}), flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
