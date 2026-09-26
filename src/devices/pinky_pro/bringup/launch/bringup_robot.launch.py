"""bringup_robot.launch.py — 실물 로봇 기동 (P0-4, A-3/A-4).

namespace 플러밍: 로봇별 토픽/TF 분리 (ROSY-CORE-SRS-001 §6).
XML $(eval) 프론트엔드 한계로 Python launch로 구현 (upload_robot.launch.py 패턴).

사용 예:
  ros2 launch bringup bringup_robot.launch.py
  ros2 launch bringup bringup_robot.launch.py namespace:=rosy_01
"""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription, Shutdown
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression

from launch_ros.actions import Node, PushRosNamespace
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    bringup_share = get_package_share_directory('bringup')
    desc_share = get_package_share_directory('description')

    namespace = LaunchConfiguration('namespace')
    use_sim_time = LaunchConfiguration('use_sim_time')
    enable_battery = LaunchConfiguration('enable_battery')
    enable_lidar = LaunchConfiguration('enable_lidar')

    # namespace 있으면 'ns/' 프레임 접두, 없으면 '' (upload_robot와 동일 패턴)
    frame_prefix = PythonExpression([
        "'", namespace, "' + ('/' if '", namespace, "' != '' else '')"
    ])
    lidar_frame = PythonExpression([
        "'", namespace, "' + ('/rplidar_link' if '", namespace, "' != '' else 'rplidar_link')"
    ])

    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value='',
                              description='로봇 namespace (예: rosy_01)'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('enable_battery', default_value='false',
                              description='Enable the rosylib I2C-1 ADC battery publisher'),
        DeclareLaunchArgument(
            'drive_enabled', default_value='true',
            description='false = no-motion mode: torque off, no cmd_vel '
                        'subscription, motor/ready stays false (D-192)',
        ),
        DeclareLaunchArgument('enable_lidar', default_value='true',
                              description='Enable the serial LiDAR driver'),
        DeclareLaunchArgument('wheel_radius', default_value='0.027'),
        DeclareLaunchArgument('wheel_separation', default_value='0.0961'),
        DeclareLaunchArgument('motor_device', default_value='/dev/ttyAMA4'),
        DeclareLaunchArgument('motor_baudrate', default_value='1000000'),
        DeclareLaunchArgument('motor_ids', default_value='[1, 2]'),
        DeclareLaunchArgument('max_linear_mps', default_value='0.20'),
        DeclareLaunchArgument('max_angular_rps', default_value='0.80'),
        DeclareLaunchArgument('max_wheel_rpm', default_value='100.0'),
        DeclareLaunchArgument('motor_profile_acceleration', default_value='200'),
        DeclareLaunchArgument(
            'cmd_vel_timeout_s', default_value='0.5',
            description='Driver-side stale cmd_vel timeout in seconds',
        ),

        # robot_state_publisher (namespace + frame_prefix 지원)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(desc_share, 'launch', 'upload_robot.launch.py')
            ),
            launch_arguments={
                'namespace': namespace,
                'is_sim': use_sim_time,
            }.items(),
        ),

        # LiDAR + bringup + battery: namespace 그룹
        GroupAction([
            PushRosNamespace(namespace),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory('sllidar_ros2'),
                        'launch', 'sllidar_c1_launch.py',
                    )
                ),
                launch_arguments={
                    'serial_port': '/dev/ttyAMA0',
                    'frame_id': lidar_frame,
                    'inverted': 'false',
                    'angle_compensate': 'true',
                    'scan_mode': 'DenseBoost',
                }.items(),
                condition=IfCondition(enable_lidar),
            ),
            Node(
                package='bringup',
                executable='bringup',
                output='screen',
                on_exit=Shutdown(reason='rosy motor node exited'),
                parameters=[{
                    'use_sim_time': use_sim_time,
                }, os.path.join(bringup_share, 'config', 'pinky_pro_adapter.yaml'),
                   os.path.join(bringup_share, 'config', 'rosy_params.yaml'), {
                    'wheel_radius': LaunchConfiguration('wheel_radius'),
                    'wheel_separation': LaunchConfiguration('wheel_separation'),
                    'cmd_vel_timeout_s': LaunchConfiguration('cmd_vel_timeout_s'),
                    'drive_enabled': ParameterValue(
                        LaunchConfiguration('drive_enabled'), value_type=bool
                    ),
                    'frame_prefix': frame_prefix,
                    'motor_device': LaunchConfiguration('motor_device'),
                    'motor_baudrate': LaunchConfiguration('motor_baudrate'),
                    'motor_ids': LaunchConfiguration('motor_ids'),
                    'max_linear_mps': LaunchConfiguration('max_linear_mps'),
                    'max_angular_rps': LaunchConfiguration('max_angular_rps'),
                    'max_wheel_rpm': LaunchConfiguration('max_wheel_rpm'),
                    'motor_profile_acceleration': LaunchConfiguration(
                        'motor_profile_acceleration'
                    ),
                }],
            ),
            Node(
                package='bringup',
                executable='battery_publisher',
                output='screen',
                parameters=[{'use_sim_time': use_sim_time}],
                condition=IfCondition(enable_battery),
            ),
        ]),
    ])
