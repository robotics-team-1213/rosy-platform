#!/usr/bin/env python3
"""D-495/D-498 sim-only copy of gz_sim map_v2_fleet_real.launch.py (model PC).

Differences from the product launch, nothing else:
1. bridge_params = d495_bridge.yaml (Gazebo scan/odom on *_gz) and d495_sim_aux.py, which
   republishes them on scan/odom (pausable: S5 odom drop, S9 scan stale), publishes the
   ground-truth pose on d495/gt and a paint-aware IR stand-in on ir_sensor/range.
2. line_observer gets IR_CALIBRATION (black = carpet, white = tape of d495_sim_aux.py) between
   the payload line_follow.yaml and the Gazebo-ground dict, so the D-491 IR guard has an
   IR_LINE observation. lane_corner_turning and camera_x_offset_m still come from the payload
   file (H1; this file overrides neither).
3. The world file is a byte copy under another name (run_sim.sh), so a peer's pkill on
   "map_v2_fleet_real.world" does not hit this run.
CORE stays on sim time with the stock overlay path (core_overlay:=...). No sim_sensors (no enforce).
"""

import math
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_HFOV_RAD = 2.0 * math.atan(160.0 / 281.6)
REAL_TILT_DEG = 8.0
REAL_CAM_MOUNT_Z = 0.0495
REAL_CAMERA_HEIGHT_M = 0.06343
IR_CALIBRATION = {"ir_calibration_enabled": True,
                  "ir_black": [600.0, 600.0, 600.0], "ir_white": [2600.0, 2600.0, 2600.0]}


def generate_launch_description():
    gz_share = get_package_share_directory("gz_sim")
    control_share = get_package_share_directory("control")
    line_config = os.path.join(control_share, "config", "line_follow.yaml")
    graph = os.path.join(control_share, "map", "map_v2_fleet", "lane_graph.yaml")

    simulation = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(os.path.join(gz_share, "launch", "launch_sim.launch.xml")),
        launch_arguments={
            "world": LaunchConfiguration("world"),
            "bridge_image": "true",
            "bridge_params": os.path.join(HERE, "d495_bridge.yaml"),
            "cam_tilt_deg": str(REAL_TILT_DEG),
            "camera_hfov": f"{REAL_HFOV_RAD:.4f}",
            "cam_mount_z": str(REAL_CAM_MOUNT_Z),
            "camera_width": "320",
            "camera_height": "240",
            "camera_update_rate": LaunchConfiguration("camera_update_rate"),
            "spawn_x": LaunchConfiguration("spawn_x"),
            "spawn_y": LaunchConfiguration("spawn_y"),
            "spawn_yaw": LaunchConfiguration("spawn_yaw"),
            "gui": "false",
            "extra_resource_path": ":" + os.path.dirname(control_share),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument("camera_update_rate", default_value="8"),
        DeclareLaunchArgument("spawn_x", default_value="-1.26955"),
        DeclareLaunchArgument("spawn_y", default_value="0.24255"),
        DeclareLaunchArgument("spawn_yaw", default_value="-1.5708"),
        DeclareLaunchArgument("camera_lane_mode", default_value="keep"),
        DeclareLaunchArgument("core_overlay"),
        # A copy of map_v2_fleet_real.world under another file name (run_sim.sh): the D-476 run
        # script on the same host pkills "gz sim.*map_v2_fleet_real.world".
        DeclareLaunchArgument("world"),
        simulation,
        ExecuteProcess(cmd=["python3", os.path.join(HERE, "d495_sim_aux.py"),
                            "--ros-args", "-p", "use_sim_time:=true"], output="screen"),
        Node(
            package="control", executable="line_observer_node", name="line_observer_node",
            output="screen",
            parameters=[line_config, IR_CALIBRATION, {
                "use_sim_time": True,
                "require_camera_controls_stable": False,
                "camera_lane_mode": ParameterValue(
                    LaunchConfiguration("camera_lane_mode"), value_type=str),
                "debug_overlay": False,
                "debug_lane_graph": graph,
                "lane_graph_path": graph,
                "camera_ground_source": "GAZEBO",
                "allow_simulation_ground": True,
                "gazebo_camera_height_m": REAL_CAMERA_HEIGHT_M,
                "gazebo_camera_pitch_rad": math.radians(REAL_TILT_DEG),
                "gazebo_camera_hfov_rad": REAL_HFOV_RAD,
                "gazebo_camera_max_range_m": 0.6,
            }],
        ),
        # D-601 in SIM (2026-10-10): front preview for Fleet's lane camera check; display JPEG only, no /clock (cost).
        Node(
            package="gz_sim", executable="sim_jpeg_relay.py", name="sim_jpeg_relay", output="screen",
            remappings=[("camera/image_raw", "camera/front")],
        ),
        Node(
            package="core", executable="core", name="core", output="screen",
            parameters=[{"use_sim_time": True}],
            additional_env={"ROSY_CONFIG": LaunchConfiguration("core_overlay"), "ROSY_DEV_AUTH": "1"},
        ),
    ])
