#!/usr/bin/env python3
"""Read-only native OMX software-path inventory; never opens or enables hardware."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

REQUIRED_PACKAGES = frozenset({
    "open_manipulator_bringup", "open_manipulator_description", "dynamixel_hardware_interface",
    "controller_manager", "joint_trajectory_controller", "joint_state_broadcaster", "omx_adapter",
})


def evaluate_runtime(*, ros_distro, expected_ros_distro, packages, actions, joint_state_publishers):
    """Report observed software gaps; publisher names are not physical provenance."""
    blockers = []
    missing = sorted(REQUIRED_PACKAGES - set(packages))
    if not ros_distro or ros_distro != expected_ros_distro:
        blockers.append("ros_distribution_mismatch")
    if missing:
        blockers.append("required_packages_missing")
    if not any("control_msgs/action/FollowJointTrajectory" in types for types in actions.values()):
        blockers.append("trajectory_action_missing")
    publishers = set(joint_state_publishers)
    if not publishers.intersection({"joint_state_broadcaster", "controller_manager"}):
        blockers.append("hardware_joint_state_source_missing")
    if publishers.intersection({"joint_state_publisher", "joint_state_publisher_gui"}):
        blockers.append("synthetic_joint_state_publisher_present")
    return {
        "software_path_available": not blockers,
        "motion_admitted": False,
        "blockers": blockers,
        "missing_packages": missing,
        "unverified": ["physical_identity", "measured_profile", "physical_feedback",
                       "independent_stop", "calibration", "payload", "recovery"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain-id", required=True, type=int, help="explicit workcell ROS domain")
    args = parser.parse_args(argv)
    if not 0 <= args.domain_id <= 232:
        parser.error("domain-id must be between 0 and 232")
    # Read the pinned target, not the basename of a possibly aliased setup path.
    import yaml
    lock = yaml.safe_load(Path(__file__).with_name("stack.lock.yaml").read_text(encoding="utf-8"))
    expected_distro = lock["target"]["ros_distro"]
    try:
        import rclpy
        from ament_index_python.packages import get_package_prefix, PackageNotFoundError
    except ImportError as error:
        print(json.dumps({"software_path_available": False, "motion_admitted": False,
                          "blockers": ["ros_python_environment_missing"], "error": str(error)}))
        return 2
    packages = set()
    for package in sorted(REQUIRED_PACKAGES):
        try:
            get_package_prefix(package)
        except PackageNotFoundError:
            continue
        packages.add(package)
    rclpy.init(domain_id=args.domain_id)
    node = None
    try:
        node = rclpy.create_node("rosy_omx_readonly_hardware_readiness")
        end = time.monotonic() + 3
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.2)
        actions = dict(node.get_action_names_and_types())
        publishers = {info.node_name for info in node.get_publishers_info_by_topic("/joint_states")}
        report = evaluate_runtime(
            ros_distro=os.environ.get("ROS_DISTRO", ""), expected_ros_distro=expected_distro,
            packages=packages, actions=actions, joint_state_publishers=publishers)
        report.update({"expected_ros_distro": expected_distro, "observed_ros_distro": os.environ.get("ROS_DISTRO"),
                       "domain_id": args.domain_id, "discovery_window_s": 3,
                       "joint_state_publishers": sorted(publishers), "observed_actions": actions,
                       "commands_sent": False,
                       "scope": "software_discovery_only_not_hardware_acceptance"})
        print(json.dumps(report, sort_keys=True))
        return 0 if report["software_path_available"] else 2
    except Exception as error:
        print(json.dumps({"software_path_available": False, "motion_admitted": False,
                          "blockers": ["runtime_discovery_failed"], "error": str(error)}))
        return 2
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
