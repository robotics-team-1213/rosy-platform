"""Capture the front camera and publish a bounded CORE preview, without motion nodes.

The line observer is observation-only too (D-2): it publishes line/observation for
CORE's camera line-follow (D-344 §9) and never commands the wheels."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


#: Per-robot IR calibration overlay (D-344 §12). Optional: absent means the
#: packaged defaults, where IR calibration stays disabled and IR_LINE fail-closed.
DEVICE_LINE_FOLLOW_CONFIG = '/etc/rosy/line_follow.yaml'


def generate_launch_description():
    config = os.path.join(get_package_share_directory('control'), 'config')
    namespace = LaunchConfiguration('namespace')
    line_params = [os.path.join(config, 'line_follow.yaml')]
    if os.path.isfile(DEVICE_LINE_FOLLOW_CONFIG):
        line_params.append(DEVICE_LINE_FOLLOW_CONFIG)
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        Node(
            package='control', executable='camera_detect_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'camera.yaml'), {'camera_backend': 'picamera2'}],
        ),
        Node(
            package='control', executable='line_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=line_params,
        ),
        Node(
            package='control', executable='road_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'line_follow.yaml')],
        ),
    ])
