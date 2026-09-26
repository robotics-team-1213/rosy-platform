"""core.launch.py — core 기동 (P1-1)."""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node


def generate_launch_description():
    default_config = os.path.join(
        get_package_share_directory("core"), "config", "rosy_default.yaml"
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "config", default_value=default_config, description="core 설정 YAML 경로"
        ),
        DeclareLaunchArgument(
            "mode", default_value="nav", choices=["nav", "slam"],
            description="Navigation/SLAM 스택 모드 (기존 web_nav2/web_slam 대체, D-3)"
        ),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"config_file": "config"}],
        ),
    ])
