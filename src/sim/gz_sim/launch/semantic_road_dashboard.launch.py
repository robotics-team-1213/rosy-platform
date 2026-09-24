#!/usr/bin/env python3
"""One-robot semantic road camera + CORE dashboard simulation."""

import math
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    gz_share = get_package_share_directory("gz_sim")
    control_share = get_package_share_directory("control")
    world = os.path.join(
        control_share, "map", "map_260905_update_v2", "worlds",
        "map_260905_traffic.world")
    line_config = os.path.join(control_share, "config", "line_follow.yaml")
    default_core_overlay = os.path.join(
        gz_share, "config", "semantic_road_core.yaml")

    simulation = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(gz_share, "launch", "launch_sim.launch.xml")),
        launch_arguments={
            "world": world,
            "bridge_image": "true",
            "cam_tilt_deg": "25",
            "camera_width": LaunchConfiguration("camera_width"),
            "camera_height": LaunchConfiguration("camera_height"),
            "camera_update_rate": LaunchConfiguration(
                "camera_update_rate"),
            "spawn_x": "-0.20",
            "spawn_y": "-0.15",
            "gui": LaunchConfiguration("gazebo_gui"),
        }.items(),
    )
    simulation_camera = {
        "use_sim_time": True,
        "require_camera_controls_stable": False,
    }

    return LaunchDescription([
        DeclareLaunchArgument("gazebo_gui", default_value="false"),
        DeclareLaunchArgument("camera_width", default_value="320"),
        DeclareLaunchArgument("camera_height", default_value="180"),
        DeclareLaunchArgument("camera_update_rate", default_value="5"),
        DeclareLaunchArgument(
            "core_overlay", default_value=default_core_overlay),
        simulation,
        Node(
            package="control",
            executable="line_observer_node",
            name="line_observer_node",
            output="screen",
            parameters=[line_config, {
                **simulation_camera,
                "camera_bright_threshold": 220,
            }],
        ),
        Node(
            package="control",
            executable="road_observer_node",
            name="road_observer_node",
            output="screen",
            parameters=[line_config, {
                **simulation_camera,
                "dashboard_source": "GAZEBO",
                "bright_threshold": 220,
                "camera_ground_mode": "gazebo_pinhole",
                "allow_simulation_ground": True,
                "gazebo_camera_height_m": 0.060194,
                "gazebo_camera_pitch_rad": math.radians(25.0),
                "gazebo_camera_hfov_rad": 1.1519,
                "gazebo_camera_max_range_m": 0.6,
            }],
        ),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"use_sim_time": True}],
            additional_env={
                "ROSY_CONFIG": LaunchConfiguration("core_overlay"),
                # D-193 7: the dev tokens below exist only with ROSY_DEV_AUTH=1.
                "ROSY_DEV_AUTH": "1"},
        ),
        LogInfo(msg=(
            "Semantic road camera dashboard: http://127.0.0.1:8080/dashboard "
            "(viewer token: rosy-dev-viewer)")),
    ])
