"""Capture the front camera and publish a bounded CORE preview, without motion nodes."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = os.path.join(get_package_share_directory('control'), 'config')
    namespace = LaunchConfiguration('namespace')
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        Node(
            package='control', executable='camera_detect_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'camera.yaml'), {'camera_backend': 'picamera2'}],
        ),
        Node(
            package='control', executable='road_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'line_follow.yaml')],
        ),
    ])
