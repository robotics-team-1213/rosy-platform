import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    robot = os.path.join(
        get_package_share_directory('control'), 'config', 'robot.yaml'
    )
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('calibration_path', default_value='',
                              description='One calibration file in the active writable data generation'),
        DeclareLaunchArgument('calibration_context_json', default_value='',
                              description='Explicit device, geometry, sensor and generation identity'),
        DeclareLaunchArgument('calibration_actor', default_value='',
                              description='Writer identity supplied by the maintenance caller'),
        Node(
            package='control',
            executable='calib_node',
            output='screen',
            namespace=LaunchConfiguration('namespace'),
            parameters=[robot, {
                'save_path': LaunchConfiguration('calibration_path'),
                'sign_path': LaunchConfiguration('calibration_path'),
                'calibration_context_json': ParameterValue(
                    LaunchConfiguration('calibration_context_json'), value_type=str),
                'calibration_actor': ParameterValue(LaunchConfiguration('calibration_actor'), value_type=str),
            }],
        ),
    ])
