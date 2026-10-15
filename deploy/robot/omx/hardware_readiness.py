#!/usr/bin/env python3
"""Read-only native OMX software-path inventory; never opens or enables hardware."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

REQUIRED_PACKAGES = frozenset({
    "open_manipulator_bringup", "open_manipulator_description", "dynamixel_hardware_interface",
    "controller_manager", "joint_trajectory_controller", "joint_state_broadcaster", "omx_adapter",
})


def evaluate_runtime(*, ros_distro, expected_ros_distro, packages, actions,
                     joint_state_publishers, namespace="/"):
    """Report observed software gaps; publisher names are not physical provenance."""
    if namespace != "/" and not re.fullmatch(r"(?:/[A-Za-z_][A-Za-z0-9_]*)+", namespace):
        raise ValueError("namespace must be an absolute ROS namespace without a trailing slash")
    prefix = namespace.rstrip("/")
    trajectory_action = prefix + "/arm_controller/follow_joint_trajectory"
    blockers = []
    missing = sorted(REQUIRED_PACKAGES - set(packages))
    if not ros_distro or ros_distro != expected_ros_distro:
        blockers.append("ros_distribution_mismatch")
    if missing:
        blockers.append("required_packages_missing")
    if "control_msgs/action/FollowJointTrajectory" not in actions.get(trajectory_action, []):
        blockers.append("trajectory_action_missing")
    publishers = set(joint_state_publishers)
    if not publishers.intersection({prefix + "/joint_state_broadcaster", prefix + "/controller_manager"}):
        blockers.append("hardware_joint_state_source_missing")
    if any(name.rsplit("/", 1)[-1] in {"joint_state_publisher", "joint_state_publisher_gui"} for name in publishers):
        blockers.append("synthetic_joint_state_publisher_present")
    return {
        "software_path_available": not blockers,
        "motion_admitted": False,
        "blockers": blockers,
        "missing_packages": missing,
        "expected_trajectory_action": trajectory_action,
        "joint_state_topic": prefix + "/joint_states",
        "unverified": ["physical_identity", "measured_profile", "physical_feedback",
                       "independent_stop", "calibration", "payload", "recovery"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain-id", required=True, type=int, help="explicit workcell ROS domain")
    parser.add_argument("--namespace", required=True, help="explicit workcell namespace, '/' for the root graph")
    args = parser.parse_args(argv)
    if not 0 <= args.domain_id <= 232:
        parser.error("domain-id must be between 0 and 232")
    node, initialized = None, False
    report = {"software_path_available": False, "motion_admitted": False}
    try:
        # Read the pinned target, not the basename of a possibly aliased setup path.
        import yaml
        lock = yaml.safe_load(Path(__file__).with_name("stack.lock.yaml").read_text(encoding="utf-8"))
        expected_distro = lock["target"]["ros_distro"]
        import rclpy
        from ament_index_python.packages import get_package_prefix, PackageNotFoundError
        packages = set()
        for package in sorted(REQUIRED_PACKAGES):
            try:
                get_package_prefix(package)
            except PackageNotFoundError:
                continue
            packages.add(package)
        rclpy.init(domain_id=args.domain_id)
        initialized = True
        node = rclpy.create_node("rosy_omx_readonly_hardware_readiness")
        end = time.monotonic() + 3
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.2)
        actions = dict(node.get_action_names_and_types())
        joint_topic = args.namespace.rstrip("/") + "/joint_states"
        publishers = {info.node_namespace.rstrip("/") + "/" + info.node_name
                      for info in node.get_publishers_info_by_topic(joint_topic)}
        report = evaluate_runtime(
            ros_distro=os.environ.get("ROS_DISTRO", ""), expected_ros_distro=expected_distro,
            packages=packages, actions=actions, joint_state_publishers=publishers, namespace=args.namespace)
        report.update({"expected_ros_distro": expected_distro, "observed_ros_distro": os.environ.get("ROS_DISTRO"),
                       "domain_id": args.domain_id, "namespace": args.namespace, "discovery_window_s": 3,
                       "joint_state_publishers": sorted(publishers), "observed_actions": actions,
                       "commands_sent": False,
                       "scope": "software_discovery_only_not_hardware_acceptance"})
    except Exception as error:
        report = {"software_path_available": False, "motion_admitted": False,
                  "blockers": ["runtime_discovery_failed"], "error": str(error)}
    finally:
        try:
            if node is not None:
                node.destroy_node()
        except Exception as error:
            print(f"readiness node cleanup failed: {error}", file=sys.stderr)
            report["software_path_available"] = False
            report.setdefault("blockers", []).append("runtime_cleanup_failed")
        if initialized:
            try:
                rclpy.shutdown()
            except Exception as error:
                print(f"readiness context cleanup failed: {error}", file=sys.stderr)
                report["software_path_available"] = False
                report.setdefault("blockers", []).append("runtime_cleanup_failed")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["software_path_available"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
