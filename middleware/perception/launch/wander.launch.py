"""Legacy wander stack. Do not launch this file beside core — CORE owns the final cmd_vel publisher (D-38/D-149)."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    cfg = os.path.join(get_package_share_directory('control'), 'config')
    robot = os.path.join(cfg, 'robot.yaml')
    return LaunchDescription([
        Node(
            package='imu_bno055',
            executable='main_node',
            name='imu_bno055',
            output='screen',
            respawn=True,
            respawn_delay=1.0,
        ),
        Node(
            package='control',
            executable='camera_detect_node',
            output='screen',
            parameters=[os.path.join(cfg, 'camera.yaml')],
            respawn=True,
            respawn_delay=1.0,
        ),
        Node(
            package='control',
            executable='safety_node',
            output='screen',
            parameters=[
                robot,
                os.path.join(cfg, 'safety.yaml'),
                os.path.join(cfg, 'cliff_calib.yaml'),
                os.path.join(cfg, 'auto_calib.yaml'),
            ],
            respawn=True,
            respawn_delay=1.0,
        ),
        Node(
            package='control',
            executable='wander_node',
            output='screen',
            parameters=[robot, os.path.join(cfg, 'wander.yaml')],
            respawn=True,
            respawn_delay=1.0,
        ),
    ])
