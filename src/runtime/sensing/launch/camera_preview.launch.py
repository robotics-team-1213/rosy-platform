"""Capture the front camera and publish a bounded CORE preview, without motion nodes.

The line observer is observation-only too (D-2): it publishes line/observation for
CORE's camera line-follow (D-344 §9) and never commands the wheels.

D-373 payload switches, both off by default (off starts nothing new):
  learned_shadow:=true  learned_lane_node, shadow only; model from shadow_pointer
  capture:=true         camera/front/compressed on, capture_trigger_node, and the
                        rosbag2 snapshot recorder (record_session --snapshot)
                        writing sessions under recording_root"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackagePrefix

SNAPSHOT_NODE = 'rosy_snapshot_recorder'  # == record_session.DEFAULT_SNAPSHOT_NODE


def generate_launch_description():
    config = os.path.join(get_package_share_directory('control'), 'config')
    namespace = LaunchConfiguration('namespace')
    learned_shadow = LaunchConfiguration('learned_shadow')
    capture = LaunchConfiguration('capture')
    recording_root = LaunchConfiguration('recording_root')
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('learned_shadow', default_value='false'),
        DeclareLaunchArgument('shadow_pointer', default_value='/var/lib/rosy/models/shadow'),
        DeclareLaunchArgument('capture', default_value='false'),
        DeclareLaunchArgument('recording_root',
                              default_value='/var/lib/rosy/camera/recordings'),
        Node(
            package='control', executable='camera_detect_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'camera.yaml'), {
                'camera_backend': 'picamera2',
                'publish_compressed': ParameterValue(capture, value_type=bool)}],
        ),
        Node(
            package='control', executable='line_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'line_follow.yaml')],
        ),
        Node(
            package='control', executable='road_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'line_follow.yaml')],
        ),
        Node(
            package='control', executable='learned_lane_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            condition=IfCondition(learned_shadow),
            parameters=[{'pointer': LaunchConfiguration('shadow_pointer')}],
        ),
        Node(
            package='control', executable='capture_trigger_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            condition=IfCondition(capture),
            parameters=[{'recording_root': recording_root,
                         'snapshot_service': f'/{SNAPSHOT_NODE}/snapshot'}],
        ),
        # Not respawned: it exits only on a full quota (2/3) or a broken ROS
        # environment (1), and says why; the trigger node then logs every
        # dropped trigger (D-62). Stopping flushes nothing (snapshot mode), so
        # the default SIGINT -> SIGTERM escalation has ample time.
        ExecuteProcess(
            cmd=[PathJoinSubstitution([FindPackagePrefix('control'), 'lib', 'control',
                                       'record_session']),
                 # "--opt=" + value keeps an empty namespace a real argument.
                 '--snapshot', ['--root=', recording_root], ['--namespace=', namespace],
                 '--node-name', SNAPSHOT_NODE],
            output='screen', condition=IfCondition(capture),
            sigterm_timeout='40',
        ),
    ])
