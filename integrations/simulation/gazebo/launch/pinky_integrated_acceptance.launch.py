#!/usr/bin/env python3
"""One-run Pinky-sized mapping, perception, and Nav2 acceptance."""

from __future__ import annotations

import os
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    OpaqueFunction,
    RegisterEventHandler,
    TimerAction,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _force_sim_time(value):
    if isinstance(value, dict):
        return {
            key: (True if key == "use_sim_time" else _force_sim_time(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_force_sim_time(item) for item in value]
    return value


def _slam_parameters(navigation_share: str) -> dict:
    source = os.path.join(navigation_share, "params", "mapper_params.yaml")
    with open(source, encoding="utf-8") as stream:
        parameters = dict(
            yaml.safe_load(stream)["slam_toolbox"]["ros__parameters"]
        )
    parameters.update({
        "use_sim_time": True,
        "scan_topic": "/scan",
        "odom_frame": "odom",
        "base_frame": "base_footprint",
        "map_frame": "map",
        "resolution": 0.02,
        "minimum_travel_distance": 0.08,
        "minimum_travel_heading": 0.10,
        "scan_buffer_size": 40,
        "use_scan_matching": False,
        "do_loop_closing": False,
        "transform_timeout": 0.5,
    })
    return {"slam_toolbox": {"ros__parameters": parameters}}


def _nav2_parameters(navigation_share: str) -> dict:
    source = os.path.join(navigation_share, "params", "nav2_params.yaml")
    with open(source, encoding="utf-8") as stream:
        parameters = _force_sim_time(yaml.safe_load(stream))
    for name in ("local_costmap", "global_costmap"):
        costmap = parameters[name][name]["ros__parameters"]
        costmap.pop("footprint", None)
        costmap.update({
            "robot_radius": 0.086,
            "footprint_padding": 0.010,
            "resolution": 0.02,
        })
        costmap["inflation_layer"]["inflation_radius"] = 0.096
    controller = parameters["controller_server"]["ros__parameters"]
    controller["general_goal_checker"].update({
        "xy_goal_tolerance": 0.05,
        "yaw_goal_tolerance": 0.20,
    })
    controller["progress_checker"].update({
        "movement_time_allowance": 30.0,
        "required_movement_radius": 0.03,
    })
    follow = controller["FollowPath"]
    follow["desired_linear_vel"] = min(
        float(follow["desired_linear_vel"]), 0.08
    )
    follow["lookahead_dist"] = 0.15
    follow["use_velocity_scaled_lookahead_dist"] = True
    return parameters


def _write_yaml(directory: str, name: str, value: dict) -> str:
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(value, stream, sort_keys=False)
    return path


def _launch_setup(context):
    gz_share = get_package_share_directory("gz_sim")
    control_share = get_package_share_directory("control")
    navigation_share = get_package_share_directory("navigation")
    run_id = LaunchConfiguration("run_id").perform(context)
    output_path = LaunchConfiguration("output_path").perform(context)
    temporary = tempfile.mkdtemp(prefix="pinky_integrated_acceptance_")
    slam_config = _write_yaml(
        temporary, "slam.yaml", _slam_parameters(navigation_share)
    )
    nav_config = _write_yaml(
        temporary, "nav2.yaml", _nav2_parameters(navigation_share)
    )
    wall_geometry = os.path.join(
        control_share,
        "map",
        "map_260905_update_v2",
        "reports",
        "wall_geometry.json",
    )
    world_path = os.path.join(
        control_share,
        "map",
        "map_260905_update_v2",
        "worlds",
        "map_260905_traffic.world",
    )
    core_overlay = os.path.join(
        gz_share, "config", "pinky_integrated_core.yaml"
    )

    base = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(os.path.join(
            gz_share, "launch", "semantic_road_dashboard.launch.py"
        )),
        launch_arguments={
            "gazebo_gui": LaunchConfiguration("gazebo_gui"),
            "camera_width": LaunchConfiguration("camera_width"),
            "camera_height": LaunchConfiguration("camera_height"),
            "camera_update_rate": LaunchConfiguration("camera_update_rate"),
            "core_overlay": core_overlay,
        }.items(),
    )
    slam = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(os.path.join(
            navigation_share, "launch", "gz_map_building.launch.xml"
        )),
        launch_arguments={
            "use_sim_time": "True",
            "slam_params_file": slam_config,
        }.items(),
    )
    mapping_runner = Node(
        package="gz_sim",
        executable="map_v2_runner.py",
        name="map_v2_runner",
        output="screen",
        parameters=[{
            "use_sim_time": True,
            "run_id": run_id,
            "start_route_index": 0,
            "exit_on_complete": True,
            "completion_zero_dwell_s": 0.5,
            "robot_diameter_m": 0.172,
        }],
    )
    navigation = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(os.path.join(
            navigation_share, "launch", "navigation_launch.xml"
        )),
        launch_arguments={
            "params_file": nav_config,
            "use_sim_time": "True",
            "autostart": "True",
            "use_composition": "False",
        }.items(),
    )
    nav_probe = Node(
        package="gz_sim",
        executable="pinky_nav2_probe.py",
        name="pinky_nav2_probe",
        output="screen",
        parameters=[{
            "use_sim_time": True,
            "run_id": run_id,
            "goal_x": -0.20,
            "goal_y": -0.15,
            "goal_yaw": 0.0,
            "max_position_error_m": 0.08,
        }],
    )
    collector = Node(
        package="gz_sim",
        executable="pinky_acceptance.py",
        name="pinky_acceptance",
        output="screen",
        parameters=[{
            "use_sim_time": True,
            "run_id": run_id,
            "output_path": output_path,
            "wall_geometry_path": wall_geometry,
            "world_path": world_path,
            "robot_radius_m": 0.086,
            "clearance_margin_m": 0.010,
            "timeout_wall_s": float(
                LaunchConfiguration("timeout_wall_s").perform(context)
            ),
        }],
    )
    return [
        base,
        collector,
        TimerAction(period=10.0, actions=[slam]),
        TimerAction(period=20.0, actions=[mapping_runner]),
        RegisterEventHandler(OnProcessExit(
            target_action=mapping_runner,
            on_exit=[navigation, nav_probe],
        )),
        RegisterEventHandler(OnProcessExit(
            target_action=collector,
            on_exit=[EmitEvent(event=Shutdown(
                reason="integrated Pinky acceptance finished"
            ))],
        )),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("run_id", default_value="pinky-integrated"),
        DeclareLaunchArgument(
            "output_path", default_value="/tmp/pinky-acceptance/result.json"
        ),
        DeclareLaunchArgument("timeout_wall_s", default_value="900.0"),
        DeclareLaunchArgument("gazebo_gui", default_value="false"),
        DeclareLaunchArgument("camera_width", default_value="320"),
        DeclareLaunchArgument("camera_height", default_value="180"),
        DeclareLaunchArgument("camera_update_rate", default_value="5"),
        OpaqueFunction(function=_launch_setup),
    ])
