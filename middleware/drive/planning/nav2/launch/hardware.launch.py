"""hardware.launch.py — Pinky hardware slice: motors + LiDAR + Nav2.

Composes bringup and Nav2 bringup. D-4 param rewrite lives in
navigation.params_rewrite. Does not start SLAM; Rosy OS FastAPI is owned
by the separate ``core`` service.
"""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import (
    AnyLaunchDescriptionSource,
    PythonLaunchDescriptionSource,
)
from launch.substitutions import AndSubstitution, LaunchConfiguration, NotSubstitution
from launch_ros.actions import Node

from navigation.footprint_profile import load_footprint_profile
from navigation.params_rewrite import write_prefixed_nav2_params
from navigation.profile_source import default_profile_path
from navigation.profile_limits import (
    load_motion_limits,
    validate_nav2_parameters,
    validate_requested_limits,
)
from navigation.site_map import resolve_keepout_mask, resolve_occupancy_map


def _opt_arg(context, name: str, default: str = "") -> str:
    try:
        return LaunchConfiguration(name).perform(context)
    except KeyError:
        return default


def _include_nav2(context, *args, **kwargs):
    nav_share = get_package_share_directory("navigation")
    namespace = LaunchConfiguration("namespace").perform(context)
    source = LaunchConfiguration("params_file").perform(context)
    backend = LaunchConfiguration("navigation_backend").perform(context).strip().lower()
    if backend not in {"localization", "slam"}:
        raise ValueError("navigation backend must be localization or slam")
    amcl_laser_model = LaunchConfiguration("amcl_laser_model").perform(context)
    if backend != "localization" and amcl_laser_model != "configured":
        raise ValueError("an AMCL laser model override requires saved-map localization")
    profile_path = LaunchConfiguration("profile_file").perform(context)
    limits = load_motion_limits(profile_path)
    footprint_file = LaunchConfiguration("footprint_profile_file").perform(context).strip()
    footprint_state = LaunchConfiguration("footprint_state").perform(context).strip().lower()
    require_footprint = LaunchConfiguration("require_measured_footprint").perform(context).lower()
    if require_footprint not in {"true", "false"}:
        raise ValueError("require_measured_footprint must be true or false")
    footprint_points = None
    state_unknown = footprint_state in {"", "unknown"}
    if require_footprint == "true" and (not footprint_file or state_unknown):
        raise ValueError(
            "a measured footprint file and non-unknown state are required"
        )
    if footprint_file and not state_unknown:
        selected_footprint = load_footprint_profile(footprint_file, footprint_state)
        if not selected_footprint.operational:
            raise ValueError(
                f"footprint state {footprint_state!r} is not measured and operational"
            )
        footprint_points = selected_footprint.footprint
        if selected_footprint.max_linear_mps is not None:
            limits = type(limits)(
                max_linear_mps=min(limits.max_linear_mps, selected_footprint.max_linear_mps),
                max_angular_rps=limits.max_angular_rps,
            )
        if selected_footprint.max_angular_rps is not None:
            limits = type(limits)(
                max_linear_mps=limits.max_linear_mps,
                max_angular_rps=min(limits.max_angular_rps, selected_footprint.max_angular_rps),
            )
    requested_linear = LaunchConfiguration("max_linear_mps").perform(context)
    requested_angular = LaunchConfiguration("max_angular_rps").perform(context)
    validate_requested_limits(
        limits, max_linear_mps=requested_linear, max_angular_rps=requested_angular
    )
    validate_nav2_parameters(source, limits)
    keepout_yaml = ""
    if backend == "localization":
        keepout_yaml = resolve_keepout_mask(_opt_arg(context, "keepout_mask"))
    # ROSY_MAX_LINEAR_MPS/ROSY_MAX_ANGULAR_RPS carry the approved speed; Nav2 plans inside it instead of CORE clipping afterwards.
    rewritten_nav = write_prefixed_nav2_params(
        source,
        namespace,
        footprint_points=footprint_points,
        speed=(float(requested_linear), float(requested_angular)),
        amcl_laser_model=amcl_laser_model,
        keepout_mask=bool(keepout_yaml),
    )
    if backend == "localization":
        fallback_map = os.path.join(nav_share, "map", "my_map.yaml")
        allow_demo_map = LaunchConfiguration("allow_demo_map").perform(context).lower()
        if allow_demo_map not in {"true", "false"}:
            raise ValueError("allow_demo_map must be true or false")
        map_yaml = resolve_occupancy_map(
            LaunchConfiguration("map").perform(context),
            fallback_map,
            allow_fallback=allow_demo_map == "true",
        )
        launch_file = "bringup_launch.xml"
        launch_arguments = {
            "namespace": namespace,
            "use_sim_time": LaunchConfiguration("use_sim_time").perform(context),
            "map": map_yaml,
            "keepout_mask": keepout_yaml,
            "params_file": rewritten_nav,
            "navigation_autostart": "False",
            # Standalone nodes are the device-verified path: on this Jazzy build
            # load_composable_node entries are silently skipped / lose the
            # namespace (2026-11-03 solution doc), so composed Nav2 never runs.
            "use_composition": "False",
        }
    else:
        mapper_source = LaunchConfiguration("mapper_params_file").perform(context)
        launch_file = "mapping_bringup_launch.xml"
        launch_arguments = {
            "namespace": namespace,
            "use_sim_time": LaunchConfiguration("use_sim_time").perform(context),
            "params_file": rewritten_nav,
            "slam_params_file": write_prefixed_nav2_params(
                mapper_source, namespace
            ),
            # Standalone nodes are the device-verified path (see above).
            "use_composition": "False",
        }
    nav2_include = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(nav_share, "launch", launch_file)
        ),
        launch_arguments=launch_arguments.items(),
    )
    if backend == "localization":
        # Only localization backend runs loc_assist; under slam, an unlocalized loc_assist masks slam_tf.
        control_share = get_package_share_directory("control")
        return [
            nav2_include,
            Node(
                package="navigation",
                executable="start_after_tf",
                namespace=namespace,
                output="screen",
                parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
                arguments=[rewritten_nav],
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(control_share, "launch", "loc_assist.launch.py")
                ),
                condition=IfCondition(LaunchConfiguration("enable_loc_assist")),
                launch_arguments={
                    "namespace": namespace,
                    "use_sim_time": LaunchConfiguration("use_sim_time").perform(context),
                    "map_yaml": map_yaml,
                }.items(),
            ),
        ]
    return [nav2_include]


def generate_launch_description():
    bringup_share = get_package_share_directory("bringup")
    nav_share = get_package_share_directory("navigation")
    control_share = get_package_share_directory("control")
    default_params = os.path.join(nav_share, "params", "nav2_params.yaml")
    default_mapper_params = os.path.join(nav_share, "params", "mapper_params.yaml")

    namespace = LaunchConfiguration("namespace")
    use_sim_time = LaunchConfiguration("use_sim_time")
    enable_line_follow = LaunchConfiguration("enable_line_follow")
    line_ir_enabled = LaunchConfiguration("line_ir_enabled")

    robot_args = {
        "namespace": namespace,
        "use_sim_time": use_sim_time,
        "enable_battery": LaunchConfiguration("enable_battery"),
        "enable_lidar": LaunchConfiguration("enable_lidar"),
        "enable_ir": AndSubstitution(line_ir_enabled, NotSubstitution(enable_line_follow)),
        "cmd_vel_timeout_s": LaunchConfiguration("cmd_vel_timeout_s"),
        "motor_device": LaunchConfiguration("motor_device"),
        "motor_baudrate": LaunchConfiguration("motor_baudrate"),
        "motor_ids": LaunchConfiguration("motor_ids"),
        "max_linear_mps": LaunchConfiguration("max_linear_mps"),
        "max_angular_rps": LaunchConfiguration("max_angular_rps"),
        "max_wheel_rpm": LaunchConfiguration("max_wheel_rpm"),
        "motor_profile_acceleration": LaunchConfiguration(
            "motor_profile_acceleration"
        ),
    }

    return LaunchDescription([
        DeclareLaunchArgument("namespace", default_value=""),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument(
            "navigation_backend",
            default_value=os.environ.get("ROSY_NAVIGATION_BACKEND", "localization"),
        ),
        # rosy-navigation Conflicts= rosy-io, so this graph is the only battery
        # reader while it runs; without it CORE power_health has no evidence.
        DeclareLaunchArgument("enable_battery", default_value="true"),
        DeclareLaunchArgument("enable_lidar", default_value="true"),
        DeclareLaunchArgument("enable_line_follow", default_value="false"),
        # D-1046 (2026-11-18 user decision): on by default for localization backend (gated in _include_nav2).
        DeclareLaunchArgument("enable_loc_assist", default_value="true"),
        DeclareLaunchArgument("line_camera_enabled", default_value="true"),
        DeclareLaunchArgument("line_ir_enabled", default_value="true"),
        DeclareLaunchArgument("camera_backend", default_value="auto"),
        DeclareLaunchArgument("camera_device", default_value="/dev/video0"),
        DeclareLaunchArgument("ir_interface", default_value="/dev/i2c-1"),
        DeclareLaunchArgument(
            "line_follow_config", default_value="/etc/rosy/line_follow.yaml"),
        DeclareLaunchArgument("cmd_vel_timeout_s", default_value="0.5"),
        DeclareLaunchArgument("motor_device", default_value="/dev/ttyAMA4"),
        DeclareLaunchArgument("motor_baudrate", default_value="1000000"),
        DeclareLaunchArgument("motor_ids", default_value="[1,2]"),
        DeclareLaunchArgument("max_linear_mps", default_value="0.20"),
        DeclareLaunchArgument("max_angular_rps", default_value="0.80"),
        DeclareLaunchArgument("max_wheel_rpm", default_value="100.0"),
        DeclareLaunchArgument("motor_profile_acceleration", default_value="200"),
        DeclareLaunchArgument(
            "map",
            default_value=os.environ.get("ROSY_MAP", "/var/lib/rosy/maps/site.yaml"),
        ),
        DeclareLaunchArgument(
            "keepout_mask",
            default_value=os.environ.get("ROSY_KEEPOUT_MASK", ""),
        ),
        DeclareLaunchArgument("params_file", default_value=default_params),
        DeclareLaunchArgument(
            "amcl_laser_model",
            default_value=os.environ.get("ROSY_AMCL_LASER_MODEL", "configured"),
        ),
        DeclareLaunchArgument("mapper_params_file", default_value=default_mapper_params),
        DeclareLaunchArgument("allow_demo_map", default_value="false"),
        DeclareLaunchArgument(
            "footprint_profile_file",
            default_value=os.environ.get(
                "ROSY_MOTION_PROFILE_FILE", ""
            ),
        ),
        DeclareLaunchArgument(
            "footprint_state",
            default_value=os.environ.get("ROSY_FOOTPRINT_STATE", "unknown"),
        ),
        DeclareLaunchArgument("require_measured_footprint", default_value="false"),
        DeclareLaunchArgument(
            "profile_file",
            default_value=default_profile_path(),
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(bringup_share, "launch", "bringup_robot.launch.py")
            ),
            launch_arguments=robot_args.items(),
        ),
        # ir_sensor/range single-publisher rule: bringup owns IR when native
        # navigation uses the separate camera service. The combined line-follow
        # graph owns it instead when that graph is enabled.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(control_share, "launch", "line_follow.launch.py")
            ),
            condition=IfCondition(enable_line_follow),
            launch_arguments={
                "namespace": namespace,
                "start_camera": LaunchConfiguration("line_camera_enabled"),
                "start_ir_adc": line_ir_enabled,
                "camera_backend": LaunchConfiguration("camera_backend"),
                "camera_device": LaunchConfiguration("camera_device"),
                "ir_interface": LaunchConfiguration("ir_interface"),
                "line_follow_config": LaunchConfiguration("line_follow_config"),
            }.items(),
        ),
        OpaqueFunction(function=_include_nav2),
    ])
