#!/usr/bin/env python3
"""One robot on the 260919 track with the real robot's camera geometry (D-364 5).

Same track as map_v2_fleet_lane.launch.py, but the scene and the camera follow
the device instead of the 2026-09-22 lap bench: grey carpet, white tape,
white 0.30 m walls with blue seam tape (map_v2_fleet_real.world), and the
the product NOMINAL camera profile (profile config camera_nominal.yaml) geometry (320x240, fx 281.6 = hfov 59.2 deg,
8 deg down, lens 0.06343 m above the floor, URDF nominal D-397). line_observer keeps the device
defaults from line_follow.yaml except for the declared Gazebo ground.
"""

import math
import os
from typing import List

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

# product NOMINAL camera profile: fx 281.6 on a 320 px row.
REAL_HFOV_RAD = 2.0 * math.atan(160.0 / 281.6)  # 1.0334 rad = 59.2 deg
REAL_TILT_DEG = 8.0
# front_camera_mount z on base_link: the URDF default (D-397 geometry.yaml), so the
# Gazebo camera sensor (front_camera_link) sits at the NOMINAL profile height at 8 deg:
# 0.028 + z - 0.015*sin(8 deg) - 0.0121*cos(8 deg) = 0.06343.
REAL_CAM_MOUNT_Z = 0.0495
REAL_CAMERA_HEIGHT_M = 0.06343
# The same chain along x: 0.020 + 0.015*cos(8 deg) - 0.0121*sin(8 deg).
REAL_CAMERA_X_OFFSET_M = 0.03317


def generate_launch_description():
    gz_share = get_package_share_directory("gz_sim")
    control_share = get_package_share_directory("control")
    world = os.path.join(
        control_share, "map", "map_v2_fleet", "worlds", "map_v2_fleet_real.world")
    line_config = os.path.join(control_share, "config", "line_follow.yaml")
    default_core_overlay = os.path.join(
        gz_share, "config", "map_v2_fleet_core.yaml")

    simulation = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(gz_share, "launch", "launch_sim.launch.xml")),
        launch_arguments={
            "world": world,
            "bridge_image": "true",
            "cam_tilt_deg": str(REAL_TILT_DEG),
            "camera_hfov": f"{REAL_HFOV_RAD:.4f}",
            "cam_mount_z": str(REAL_CAM_MOUNT_Z),
            "camera_width": "320",
            "camera_height": "240",
            "camera_update_rate": LaunchConfiguration("camera_update_rate"),
            "spawn_x": LaunchConfiguration("spawn_x"),
            "spawn_y": LaunchConfiguration("spawn_y"),
            "spawn_yaw": LaunchConfiguration("spawn_yaw"),
            "gui": LaunchConfiguration("gazebo_gui"),
            # model://control/... (lane mesh, carpet texture) needs the
            # control share on GZ_SIM_RESOURCE_PATH, as in the lap launch.
            "extra_resource_path": ":" + os.path.dirname(control_share),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument("gazebo_gui", default_value="false"),
        # The device streams 8 fps (teleop_20260919_151213).
        DeclareLaunchArgument("camera_update_rate", default_value="8"),
        DeclareLaunchArgument("spawn_x", default_value="-1.26955"),
        DeclareLaunchArgument("spawn_y", default_value="0.24255"),
        DeclareLaunchArgument("spawn_yaw", default_value="-1.5708"),
        # Any mode string line_observer accepts (edge_left, lane, keep, ...).
        DeclareLaunchArgument("camera_lane_mode", default_value="edge_left"),
        DeclareLaunchArgument("debug_overlay", default_value="false"),
        DeclareLaunchArgument("core_overlay", default_value=default_core_overlay),
        DeclareLaunchArgument("route", default_value="[]"),
        DeclareLaunchArgument("route_start", default_value="[]"),
        simulation,
        Node(
            package="control",
            executable="line_observer_node",
            name="line_observer_node",
            output="screen",
            parameters=[line_config, {
                "use_sim_time": True,
                # Gazebo has no camera controls to report stable.
                "require_camera_controls_stable": False,
                "camera_lane_mode": ParameterValue(
                    LaunchConfiguration("camera_lane_mode"), value_type=str),
                "debug_overlay": ParameterValue(
                    LaunchConfiguration("debug_overlay"), value_type=bool),
                "debug_lane_graph": os.path.join(
                    control_share, "map", "map_v2_fleet", "lane_graph.yaml"),
                "lane_graph_path": os.path.join(
                    control_share, "map", "map_v2_fleet", "lane_graph.yaml"),
                "route": ParameterValue(
                    LaunchConfiguration("route"), value_type=List[str]),
                "route_start": ParameterValue(
                    LaunchConfiguration("route_start"), value_type=List[float]),
                "camera_ground_source": "GAZEBO",
                "allow_simulation_ground": True,
                "gazebo_camera_height_m": REAL_CAMERA_HEIGHT_M,
                "gazebo_camera_pitch_rad": math.radians(REAL_TILT_DEG),
                "gazebo_camera_hfov_rad": REAL_HFOV_RAD,
                "gazebo_camera_max_range_m": 0.6,
                "lane_corner_turning": True,
                "camera_x_offset_m": REAL_CAMERA_X_OFFSET_M,
            }],
        ),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"use_sim_time": True}],
            # D-193 7: the dev tokens below exist only with ROSY_DEV_AUTH=1.
            additional_env={"ROSY_CONFIG": LaunchConfiguration("core_overlay"), "ROSY_DEV_AUTH": "1"},
        ),
        LogInfo(msg=(
            "map_v2_fleet REAL-profile sim: http://127.0.0.1:8080/dashboard "
            "(viewer token: rosy-dev-viewer). Start: PUT /api/v1/line-follow/mode "
            "{\"mode\": \"CAMERA_LINE\"} with the operator token.")),
    ])
