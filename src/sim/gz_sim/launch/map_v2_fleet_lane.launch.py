#!/usr/bin/env python3
"""One Pinky on the 260919 road track: camera lane evidence into CORE."""

import math
import os
from typing import List

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


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
            "spawn_x": LaunchConfiguration("spawn_x"),
            "spawn_y": LaunchConfiguration("spawn_y"),
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
        DeclareLaunchArgument("spawn_x", default_value="-1.26955"),
        DeclareLaunchArgument("spawn_y", default_value="0.24255"),
        # -pi/2 faces ROS -y along the left lane (toward the crosswalk).
        DeclareLaunchArgument("spawn_yaw", default_value="-1.5708"),
        DeclareLaunchArgument("camera_lane_mode", default_value="edge_left"),
        DeclareLaunchArgument("debug_overlay", default_value="false"),
        DeclareLaunchArgument("core_overlay", default_value=default_core_overlay),
        # route_a/route_b/route_ab only (junction followers, Task 6). Empty by
        # default so every other mode is unaffected. Encoded as a YAML flow
        # list on the command line, e.g. route:='[west:f, ring_w:f]' and
        # route_start:='[-1.26955, 0.24255, -1.5708]'; ParameterValue below
        # parses that string into the node's declared string/double array
        # parameters with yaml.safe_load.
        DeclareLaunchArgument("route", default_value="[]"),
        DeclareLaunchArgument("route_start", default_value="[]"),
        # Stage 3 (parking): observe the wedge tag (world model dock_tag_7) on
        # dock/observation for CORE's parking dock. Off by default so stages
        # 1-2 run exactly as before.
        DeclareLaunchArgument("dock_observer", default_value="false"),
        simulation,
        Node(
            package="control",
            executable="line_observer_node",
            name="line_observer_node",
            output="screen",
            parameters=[line_config, {
                "use_sim_time": True,
                "require_camera_controls_stable": False,
                # Rendered grey: floor ~103-110, paint 228 near dimming to 214
                # at 0.44 m (run 193728). The body (~218, rows >= 139) lies
                # nearer than edge_left's bird's-eye view samples, so 180
                # (midway) keeps the far paint that 220 lost.
                "camera_bright_threshold": 180,
                # Hold the inner block's outline (the lap's left boundary) a
                # half-width off in bird's-eye view: row-wise pairing stopped
                # at the 65 deg bends (run 184434). Declared Gazebo camera
                # geometry (tilt 25 deg, 320x180).
                "camera_lane_mode": ParameterValue(
                    LaunchConfiguration("camera_lane_mode"), value_type=str),
                "debug_overlay": ParameterValue(
                    LaunchConfiguration("debug_overlay"), value_type=bool),
                "debug_lane_graph": os.path.join(
                    control_share, "map", "map_v2_fleet", "lane_graph.yaml"),
                # route_a/route_b/route_ab only; every other mode ignores these.
                "lane_graph_path": os.path.join(
                    control_share, "map", "map_v2_fleet", "lane_graph.yaml"),
                "route": ParameterValue(
                    LaunchConfiguration("route"), value_type=List[str]),
                "route_start": ParameterValue(
                    LaunchConfiguration("route_start"), value_type=List[float]),
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
            package="control",
            executable="dock_observer_node",
            name="dock_observer_node",
            output="screen",
            condition=IfCondition(LaunchConfiguration("dock_observer")),
            parameters=[{
                "use_sim_time": True,
                # Declared Gazebo camera: front_camera_link on base_footprint
                # from the URDF chain, as gz sdf -p places the sensor
                # (0.0284809, 0, 0.0601944): 0.020 + 0.015*cos(25 deg)
                # - 0.0121*sin(25 deg) ahead, 0.028 + 0.0495
                # - 0.015*sin(25 deg) - 0.0121*cos(25 deg) high.
                "camera_geometry_source": "GAZEBO",
                "camera_height_m": 0.060194,
                "camera_pitch_rad": math.radians(25.0),
                "camera_hfov_rad": 1.1519,
                "camera_x_offset_m": 0.028481,
                "tag_id": 7,
                "tag_size_m": 0.05,
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
            "map_v2_fleet lane sim: http://127.0.0.1:8080/dashboard "
            "(viewer token: rosy-dev-viewer). Start: PUT /api/v1/line-follow/mode "
            "{\"mode\": \"CAMERA_LINE\"} with the operator token.")),
    ])
