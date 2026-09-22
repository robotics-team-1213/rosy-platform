#!/usr/bin/env python3
"""One Pinky on the 260919 road track: camera lane evidence into CORE."""

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
        control_share, "map", "map_v2_fleet", "worlds", "map_v2_fleet.world")
    line_config = os.path.join(control_share, "config", "line_follow.yaml")
    default_core_overlay = os.path.join(
        gz_share, "config", "map_v2_fleet_core.yaml")

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
            "spawn_x": "-1.26955",
            "spawn_y": "0.24255",
            "spawn_yaw": LaunchConfiguration("spawn_yaw"),
            "gui": LaunchConfiguration("gazebo_gui"),
            # The world's model://control/map/map_v2_fleet/meshes/road_lines.stl
            # lane mesh needs the control share on GZ_SIM_RESOURCE_PATH.
            # launch_sim.launch.xml's default only resolves via the
            # `description` share, which has no sibling `control/` dir under
            # colcon's default isolated (--symlink-install) layout.
            "extra_resource_path": ":" + os.path.dirname(control_share),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument("gazebo_gui", default_value="false"),
        DeclareLaunchArgument("camera_width", default_value="320"),
        DeclareLaunchArgument("camera_height", default_value="180"),
        DeclareLaunchArgument("camera_update_rate", default_value="5"),
        # -pi/2 faces ROS -y along the left lane (toward the crosswalk).
        DeclareLaunchArgument("spawn_yaw", default_value="-1.5708"),
        DeclareLaunchArgument("core_overlay", default_value=default_core_overlay),
        simulation,
        Node(
            package="control",
            executable="line_observer_node",
            name="line_observer_node",
            output="screen",
            parameters=[line_config, {
                "use_sim_time": True,
                "require_camera_controls_stable": False,
                # Rendered grey: floor ~109, robot body in the bottom rows ~218,
                # lane paint ~224-228. 220 keeps the body out of the line mask.
                "camera_bright_threshold": 220,
                # Hold the inner block's outline (the lap's left boundary) a
                # half-width off in bird's-eye view: row-wise pairing stopped
                # at the 65 deg bends (run 184434). Declared Gazebo camera
                # geometry (tilt 25 deg, 320x180).
                "camera_lane_mode": "edge_left",
                "camera_ground_source": "GAZEBO",
                "allow_simulation_ground": True,
                "gazebo_camera_height_m": 0.060194,
                "gazebo_camera_pitch_rad": math.radians(25.0),
                "gazebo_camera_hfov_rad": 1.1519,
                "gazebo_camera_max_range_m": 0.6,
                "camera_roi_top_fraction": 0.25,
                "camera_roi_bottom_fraction": 0.75,
                # Crosswalk bars light ~50% of the band (run 164241); 0.75 still
                # rejects a washed-out frame.
                "camera_washed_fraction": 0.75,
                # 90 deg corners: odometry-bounded turn; the URDF camera sits
                # 0.020 + 0.015*cos(25 deg) = 0.034 m ahead of base_link.
                "lane_corner_turning": True,
                "camera_x_offset_m": 0.034,
            }],
        ),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"use_sim_time": True}],
            additional_env={"ROSY_CONFIG": LaunchConfiguration("core_overlay")},
        ),
        LogInfo(msg=(
            "map_v2_fleet lane sim: http://127.0.0.1:8080/dashboard "
            "(viewer token: rosy-dev-viewer). Start: PUT /api/v1/line-follow/mode "
            "{\"mode\": \"CAMERA_LINE\"} with the operator token.")),
    ])
