"""ROS topics and geometry for the single-robot Isaac Sim graph."""

import re


def robot_contract(namespace: str) -> dict:
    if not re.fullmatch(r"rosy_(0[1-9]|[1-9][0-9])", namespace):
        raise ValueError("namespace must be rosy_01 through rosy_99")
    return {
        "namespace": namespace,
        "command_topic": "cmd_vel",
        "odom_topic": "odom",
        "odom_frame": f"{namespace}/odom",
        "base_frame": f"{namespace}/base_footprint",
        "wheel_joints": ("l_wheel_joint", "r_wheel_joint"),
        "wheel_radius": 0.028,
        "wheel_distance": 0.0961,
        "max_linear_speed": 0.2,
        "max_angular_speed": 0.8,
    }
