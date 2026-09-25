"""Sensing-only D-143 line observer; CORE retains all command authority."""
# ir_sensor/range single-publisher rule: this launch starts the Python
# ir_adc_node as the only IR publisher on the bus. The C++ sensor_adc node
# (legacy bench) speaks the same register protocol on the same bus — running
# both interleaves arrays from two readers. Never start them together.

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('control')
    config = os.path.join(share, 'config')
    namespace = LaunchConfiguration('namespace')
    start_camera = LaunchConfiguration('start_camera')
    start_ir_adc = LaunchConfiguration('start_ir_adc')
    line_follow_config = LaunchConfiguration('line_follow_config')
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('start_camera', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('start_ir_adc', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('camera_backend', default_value='auto'),
        DeclareLaunchArgument('camera_device', default_value='/dev/video0'),
        DeclareLaunchArgument('ir_interface', default_value='/dev/i2c-1'),
        DeclareLaunchArgument(
            'line_follow_config',
            default_value=os.path.join(config, 'line_follow.yaml')),
        Node(
            package='control', executable='ir_adc_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=1.0,
            condition=IfCondition(start_ir_adc),
            parameters=[line_follow_config, {
                'interface': LaunchConfiguration('ir_interface'),
            }],
        ),
        Node(
            package='control', executable='camera_detect_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=1.0,
            condition=IfCondition(start_camera),
            parameters=[os.path.join(config, 'camera.yaml'), {
                'camera_backend': LaunchConfiguration('camera_backend'),
                'camera_device': LaunchConfiguration('camera_device'),
            }],
        ),
        Node(
            package='control', executable='line_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=1.0,
            parameters=[line_follow_config],
        ),
        Node(
            package='control', executable='road_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=1.0,
            parameters=[line_follow_config],
        ),
    ])
