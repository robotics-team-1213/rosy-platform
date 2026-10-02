"""Capture the front camera and publish a bounded CORE preview, without motion nodes.

The line observer is observation-only too (D-2): it publishes line/observation for
CORE's camera line-follow (D-344 §9) and never commands the wheels.

D-373 payload switches, both off by default (off starts nothing new):
  learned_shadow:=true  learned_lane_node, shadow only; model from shadow_pointer
  capture:=true         camera/front/compressed on, capture_trigger_node, and the
                        rosbag2 snapshot recorder (record_session --snapshot)
                        writing sessions under recording_root
On the device both default from ROSY_LEARNED_SHADOW / ROSY_CAPTURE, which
rosy-camera.service reads from the optional /etc/rosy/learned-perception.env.
Only "true" and "false" count; anything else is off, with a warning (D-62).
learned_max_rate_hz (ROSY_LEARNED_MAX_HZ, default 3.0; 0 = every frame) caps
how often learned_lane_node infers: a Pi 5 at the full 8 fps was ~175 % CPU."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo
from launch.conditions import IfCondition
from launch.logging import get_logger
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackagePrefix

from control.ir_overlay import usable_overlay


def _env_switch(name):
    value = os.environ.get(name, 'false')
    if value in ('true', 'false'):
        return value
    get_logger('camera_preview.launch').warning(
        f'{name}={value!r} is not "true" or "false"; treating it as false')
    return 'false'


def _env_rate(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        rate = float(value)
    except ValueError:
        rate = -1.0
    if 0.0 <= rate < float('inf'):
        return str(rate)
    get_logger('camera_preview.launch').warning(
        f'{name}={value!r} is not a rate >= 0 in Hz; using {default}')
    return default


def generate_launch_description():
    config = os.path.join(get_package_share_directory('control'), 'config')
    namespace = LaunchConfiguration('namespace')
    learned_shadow = LaunchConfiguration('learned_shadow')
    capture = LaunchConfiguration('capture')
    recording_root = LaunchConfiguration('recording_root')
    pilot_recording_root = LaunchConfiguration('pilot_recording_root')
    line_params = [os.path.join(config, 'line_follow.yaml')]
    # D-344 §12: optional per-robot IR calibration overlay, validated here so a
    # malformed file is skipped (IR_LINE stays fail-closed) instead of crash-looping
    # the observer that CORE's camera line-follow depends on.
    overlay, overlay_note = usable_overlay()
    if overlay is not None:
        line_params.append(overlay)
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('learned_shadow',
                              default_value=_env_switch('ROSY_LEARNED_SHADOW')),
        DeclareLaunchArgument('shadow_pointer', default_value='/var/lib/rosy/models/shadow'),
        DeclareLaunchArgument('learned_max_rate_hz',
                              default_value=_env_rate('ROSY_LEARNED_MAX_HZ', '3.0')),
        DeclareLaunchArgument('capture', default_value=_env_switch('ROSY_CAPTURE')),
        DeclareLaunchArgument('recording_root',
                              default_value='/var/lib/rosy/camera/recordings'),
        DeclareLaunchArgument('pilot_recording_root', default_value='/var/lib/rosy/pilot-recordings'),
        LogInfo(msg=f'IR calibration overlay: {overlay_note}'),
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
            parameters=line_params,
        ),
        Node(
            package='control', executable='road_observer_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            parameters=[os.path.join(config, 'line_follow.yaml')],
        ),
        # D-411 A: Pilot recording, idle until CORE asks; evidence only (no command topic).
        # Respawned: on start it stops a writer its predecessor left and finishes that session.
        Node(package='control', executable='pilot_recorder_node', name='pilot_recorder_node',
             namespace=namespace, output='screen', respawn=True, respawn_delay=2.0,
             parameters=[{'recording_root': pilot_recording_root}]),
        Node(
            package='control', executable='learned_lane_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            condition=IfCondition(learned_shadow),
            parameters=[{'pointer': LaunchConfiguration('shadow_pointer'),
                         'max_rate_hz': ParameterValue(LaunchConfiguration('learned_max_rate_hz'),
                                                       value_type=float)}],
        ),
        Node(
            package='control', executable='capture_trigger_node', namespace=namespace,
            output='screen', respawn=True, respawn_delay=2.0,
            condition=IfCondition(capture),
            # The recorder service name follows the namespace on both sides
            # (control.recording.snapshot_node_name), so robots sharing a
            # domain do not collide.
            parameters=[{'recording_root': recording_root}],
        ),
        # Not respawned: it exits only on a full quota (2/3) or a broken ROS
        # environment (1), and says why; the trigger node then logs every
        # dropped trigger (D-62). Stopping flushes nothing (snapshot mode), so
        # the default SIGINT -> SIGTERM escalation has ample time.
        ExecuteProcess(
            cmd=[PathJoinSubstitution([FindPackagePrefix('control'), 'lib', 'control',
                                       'record_session']),
                 # "--opt=" + value keeps an empty namespace a real argument.
                 '--snapshot', ['--root=', recording_root], ['--namespace=', namespace]],
            output='screen', condition=IfCondition(capture),
            sigterm_timeout='40',
        ),
    ])
