"""core.launch.py — core 기동 (P1-1)."""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_config = os.path.join(
        get_package_share_directory("core_common"), "config", "rosy_default.yaml"
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "config", default_value=default_config, description="core 설정 YAML 경로"
        ),
        DeclareLaunchArgument(
            "mode", default_value="nav", choices=["nav", "slam"],
            description="Navigation/SLAM 스택 모드 (기존 web_nav2/web_slam 대체, D-3)"
        ),
        DeclareLaunchArgument(
            "log_level", default_value="info",
            choices=["debug", "info", "warn", "error", "fatal"],
            description="core 노드 로그 레벨"
        ),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"config_file": "config"}],
            # core 로거만 바꾼다. 전역으로 주면 rcl/DDS 로그까지 debug가 된다.
            arguments=["--ros-args", "--log-level", ["core:=", LaunchConfiguration("log_level")]],
        ),
    ])
