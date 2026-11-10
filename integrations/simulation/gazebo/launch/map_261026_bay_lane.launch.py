#!/usr/bin/env python3
"""One Pinky on the 261026 track parking area: pink guide-tape camera evidence
into CORE (D-1013 gate b). Keep mode with paint_source pink; the bay pit-in
docking approach is a later branch, so no dock observer here."""

import math
import os
import sys

_LAUNCH_DIR = os.path.dirname(os.path.abspath(__file__))
if _LAUNCH_DIR not in sys.path:
    sys.path.insert(0, _LAUNCH_DIR)
from gz_multi_parts import observer_steering_law

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    gz_share = get_package_share_directory("gz_sim")
    control_share = get_package_share_directory("control")
    world = os.path.join(
        control_share, "map", "map_world_261026", "worlds", "map_world_261026.world")
    line_config = os.path.join(control_share, "config", "line_follow.yaml")
    default_core_overlay = os.path.join(
        gz_share, "config", "map_261026_core.yaml")

    simulation = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(gz_share, "launch", "launch_sim.launch.xml")),
        launch_arguments={
            "world": world,
            "bridge_image": "true",
            "cam_tilt_deg": "25",
            "camera_width": LaunchConfiguration("camera_width"),
            "camera_height": LaunchConfiguration("camera_height"),
            "camera_update_rate": LaunchConfiguration("camera_update_rate"),
            "spawn_x": LaunchConfiguration("spawn_x"),
            "spawn_y": LaunchConfiguration("spawn_y"),
            "spawn_yaw": LaunchConfiguration("spawn_yaw"),
            "gui": LaunchConfiguration("gazebo_gui"),
            # The world's model://control/map/map_world_261026 mesh needs the
            # control share on GZ_SIM_RESOURCE_PATH (same isolated-layout reason
            # as map_v2_fleet_lane).
            "extra_resource_path": ":" + os.path.dirname(control_share),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument("gazebo_gui", default_value="false"),
        DeclareLaunchArgument("camera_width", default_value="320"),
        DeclareLaunchArgument("camera_height", default_value="180"),
        DeclareLaunchArgument("camera_update_rate", default_value="5"),
        # S2 (parking entrance stop): facing +y along the pink guide curve
        # toward P3 (graph v7).
        DeclareLaunchArgument("spawn_x", default_value="0.309"),
        DeclareLaunchArgument("spawn_y", default_value="-0.13"),
        DeclareLaunchArgument("spawn_yaw", default_value="1.5708"),
        DeclareLaunchArgument("camera_lane_mode", default_value="keep"),
        DeclareLaunchArgument("debug_overlay", default_value="false"),
        DeclareLaunchArgument("core_overlay", default_value=default_core_overlay),
        simulation,
        OpaqueFunction(function=_line_observer, kwargs={"line_config": line_config}),
        # D-601 in SIM: CORE's front preview (vision/front/status) from the
        # Gazebo camera. Display JPEG only; no road/observation.
        Node(
            package="gz_sim",
            executable="sim_jpeg_relay.py",
            name="sim_jpeg_relay",
            output="screen",
            remappings=[("camera/image_raw", "camera/front")],
        ),
        Node(package="gz_sim", executable="sim_battery.py", name="sim_battery", output="screen"),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"use_sim_time": True}],
            additional_env={"ROSY_CONFIG": LaunchConfiguration("core_overlay"), "ROSY_DEV_AUTH": "1"},
        ),
        LogInfo(msg=(
            "map_261026 bay lane sim: http://127.0.0.1:8080/dashboard "
            "(viewer token: rosy-dev-viewer). Start: PUT /api/v1/line-follow/mode "
            "{\"mode\": \"CAMERA_LINE\"} with the operator token.")),
    ])


def _line_observer(context, *, line_config):
    return [
        Node(
            package="control",
            executable="line_observer_node",
            name="line_observer_node",
            output="screen",
            parameters=[line_config, {
                "use_sim_time": True,
                "require_camera_controls_stable": False,
                # D-1013: the guide is magenta tape, not bright paint; keep
                # mode consumes the pink HSV paint mask directly, so the white
                # threshold below only matters if paint_source ever reverts.
                "paint_source": "pink",
                "camera_bright_threshold": 180,
                "camera_lane_mode": ParameterValue(
                    LaunchConfiguration("camera_lane_mode"), value_type=str),
                "debug_overlay": ParameterValue(
                    LaunchConfiguration("debug_overlay"), value_type=bool),
                "camera_ground_source": "GAZEBO",
                "allow_simulation_ground": True,
                "gazebo_camera_height_m": 0.060194,
                "gazebo_camera_pitch_rad": math.radians(25.0),
                "gazebo_camera_hfov_rad": 1.1519,
                "gazebo_camera_max_range_m": 0.6,
                "camera_roi_top_fraction": 0.25,
                "camera_roi_bottom_fraction": 0.75,
                "camera_washed_fraction": 0.75,
                "lane_corner_turning": True,
                "camera_x_offset_m": 0.028481,
            }, observer_steering_law(LaunchConfiguration("core_overlay").perform(context))],
        )
    ]
