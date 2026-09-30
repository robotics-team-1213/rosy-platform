"""D-356 shadow inference of a learned lane model; publishes evidence only."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('pointer', default_value='/var/lib/rosy/models/shadow'),
        Node(
            package='control', executable='learned_lane_node',
            namespace=LaunchConfiguration('namespace'), output='screen',
            parameters=[{'pointer': LaunchConfiguration('pointer')}],
        ),
    ])
