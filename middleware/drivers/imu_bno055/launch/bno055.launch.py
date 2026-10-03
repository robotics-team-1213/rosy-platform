"""Launch the optional BNO055 driver after explicit Device commissioning."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_params = os.path.join(
        get_package_share_directory("imu_bno055"), "config", "bno055.yaml"
    )
    return LaunchDescription([
        DeclareLaunchArgument("interface", default_value="/dev/i2c-0"),
        DeclareLaunchArgument("frame_id", default_value="imu_link"),
        DeclareLaunchArgument("rate", default_value="100.0"),
        DeclareLaunchArgument("reset_on_start", default_value="false"),
        DeclareLaunchArgument("orientation_stddev_rad", default_value="0.0"),
        DeclareLaunchArgument("angular_velocity_stddev_deg_s", default_value="0.0"),
        DeclareLaunchArgument("linear_acceleration_stddev_mps2", default_value="0.0"),
        Node(
            package="imu_bno055",
            executable="main_node",
            name="imu_bno055",
            output="screen",
            parameters=[
                default_params,
                {
                    "interface": LaunchConfiguration("interface"),
                    "frame_id": LaunchConfiguration("frame_id"),
                    "rate": ParameterValue(
                        LaunchConfiguration("rate"), value_type=float
                    ),
                    "reset_on_start": ParameterValue(
                        LaunchConfiguration("reset_on_start"), value_type=bool
                    ),
                    "orientation_stddev_rad": ParameterValue(
                        LaunchConfiguration("orientation_stddev_rad"), value_type=float
                    ),
                    "angular_velocity_stddev_deg_s": ParameterValue(
                        LaunchConfiguration("angular_velocity_stddev_deg_s"),
                        value_type=float,
                    ),
                    "linear_acceleration_stddev_mps2": ParameterValue(
                        LaunchConfiguration("linear_acceleration_stddev_mps2"),
                        value_type=float,
                    ),
                },
            ],
        ),
    ])
