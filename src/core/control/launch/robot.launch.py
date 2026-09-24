"""LEGACY_FULL_STACK: Select processing features; hardware bringup and ADC are separate prerequisites.

Do not launch profile:=full beside core. That profile starts safety_node, the
legacy final cmd_vel publisher. profile:=sensing starts no Twist publisher.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction, TimerAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from control.control.startup_profile import FEATURES, startup_profile


def _share(pkg, *parts):
    return os.path.join(get_package_share_directory(pkg), *parts)


def _processing_actions(context):
    """Resolve selection before optional package lookup or process construction."""
    selected = startup_profile(
        LaunchConfiguration('profile').perform(context),
        {name: LaunchConfiguration('start_' + name).perform(context) for name in FEATURES},
        LaunchConfiguration('calibration_sensing_only').perform(context))
    enabled = selected['nodes']
    robot = _share('control', 'config', 'robot.yaml')
    cfg = _share('control', 'config')

    def node(executable, parameters, package='control', **kwargs):
        return Node(package=package, executable=executable, output='screen',
                    parameters=parameters, respawn=True, respawn_delay=1.0, **kwargs)

    actions = [LogInfo(msg='robot.launch selected processes: ' + ', '.join(
        name for name, value in enabled.items() if value) +
        '; disabled: ' + ', '.join(name for name, value in enabled.items() if not value) +
        f"; calibration_sensing_only={selected['calibration_sensing_only']}. " +
        'Delays order startup only; sensor and calibration gates determine readiness.')]
    if enabled['imu']:
        actions.append(node('main_node', [], package='imu_bno055', name='imu_bno055'))
    if enabled['camera']:
        actions.append(node('camera_detect_node', [robot, os.path.join(cfg, 'camera.yaml')]))
    if enabled['safety']:
        safety = node('safety_node', [robot, os.path.join(cfg, 'safety.yaml'),
            os.path.join(cfg, 'cliff_calib.yaml'), os.path.join(cfg, 'auto_calib.yaml'),
            {'localization_required': LaunchConfiguration('localization_required')}])
        actions.append(TimerAction(period=1.5, actions=[safety]))
    if enabled['wander']:
        actions.append(TimerAction(period=3.0, actions=[
            node('wander_node', [robot, os.path.join(cfg, 'wander.yaml')])]))
    displays = []
    if enabled['lcd']:
        # lcd_control 은 흡수되어 apps/emotion(emotion/emotion_server)이 됐다.
        # 감정 표시 노드는 CORE 의 display/info 를 구독하는 별도 프로세스로
        # 실행한다 — 여기서 대신 시작하지 않는다.
        displays.append(LogInfo(msg='lcd_control was absorbed as apps/emotion; launch it separately'))
    if enabled['web']:
        web_params = [robot, os.path.join(cfg, 'web.yaml')]
        web_port = LaunchConfiguration('web_port').perform(context)
        web_backend = LaunchConfiguration('web_backend_port').perform(context)
        if web_port:
            web_params.append({'port': int(web_port)})
        if web_backend:
            web_params.append({'backend_port': int(web_backend)})
        displays.append(node('web_node', web_params))
    if enabled['watch']:
        displays.append(node('watch_node', [robot, {'hz': 1.0, 'once': False}]))
        actions.append(LogInfo(msg='watch_node checks the full hardware graph; disabled feature nodes remain reported missing.'))
    if displays:
        actions.append(TimerAction(period=3.5, actions=displays))
    if enabled['calibration']:
        actions.append(TimerAction(period=4.0, actions=[node('startup_calibration_node',
            [robot, {'calibration_sensing_only': selected['calibration_sensing_only']}])]))
    return actions


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('profile', default_value='full', choices=['full', 'sensing']),
        DeclareLaunchArgument('localization_required', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('calibration_sensing_only', default_value='auto', choices=['auto', 'true', 'false']),
        DeclareLaunchArgument('web_port', default_value=''),
        DeclareLaunchArgument('web_backend_port', default_value=''),
    ]
    arguments += [DeclareLaunchArgument('start_' + name, default_value='auto',
                  choices=['auto', 'true', 'false']) for name in FEATURES]
    return LaunchDescription(arguments + [OpaqueFunction(function=_processing_actions)])
