"""map_v2_fleet lane launch keeps CORE the only final cmd_vel publisher."""

import xml.etree.ElementTree as ET
from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "map_v2_fleet_lane.launch.py"
LAUNCH_SIM = Path(__file__).resolve().parents[1] / "launch" / "launch_sim.launch.xml"


def test_launch_uses_the_catalogued_world_and_spawn():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet", "worlds", "map_v2_fleet.world"' in source
    assert 'DeclareLaunchArgument("spawn_x", default_value="-1.26955")' in source
    assert 'DeclareLaunchArgument("spawn_y", default_value="0.24255")' in source
    assert '"bridge_image": "true"' in source


def test_line_observer_threshold_sits_between_floor_and_far_paint():
    """Run 161132: floor 109, the robot's body 218 in rows >= 139, near paint
    224-228; row-wise modes needed 220 to keep the body out. edge_left never
    samples those rows (bird's-eye view starts at 0.09 m, the body ends at
    0.083 m), and run 193728 showed paint dimming to 214 at 0.44 m, so at 220
    the left line was 0.14 m long and never seeded. 180 sits midway."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("camera_lane_mode", default_value="edge_left")' in source
    assert '"camera_bright_threshold": 180' in source


def test_only_core_can_command_motion():
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'executable="core"' in source
    assert "cmd_vel" not in source
    assert "road_observer_node" not in source  # needs a map_v2_fleet road scene first


def test_core_serves_the_dev_tokens_the_launch_message_names():
    # D-193 7: the packaged defaults carry no tokens; the sim opts in.
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"ROSY_DEV_AUTH": "1"' in source
    assert "rosy-dev-viewer" in source


def test_launch_sim_is_well_formed_xml():
    """ros2 launch rejects the file outright if it is not XML (e.g. "--" in a comment)."""
    ET.parse(LAUNCH_SIM)


def test_lane_mesh_resource_path_reaches_the_control_share():
    """The world's model://control/... lane mesh needs the control share on
    GZ_SIM_RESOURCE_PATH. launch_sim.launch.xml's default set_env only ever
    resolves via the `description` share, which has no `control/` dir under
    colcon's default isolated (--symlink-install) layout, so the mesh would
    silently fail to load unless this launch adds the control share too."""
    launch_sim = LAUNCH_SIM.read_text(encoding="utf-8")
    assert 'name="extra_resource_path"' in launch_sim
    assert "$(var extra_resource_path)" in launch_sim

    source = LAUNCH.read_text(encoding="utf-8")
    assert '"extra_resource_path"' in source
    assert "os.path.dirname(control_share)" in source


def test_core_overlay_does_not_wait_for_a_road_scene_this_map_lacks():
    """ENFORCED traffic policy holds at zero until road evidence arrives
    (traffic_policy/manager.py set_mode -> HOLD no_road_evidence). This launch
    runs no road observer, so the map's own overlay must keep the policy off
    instead of borrowing map_260905's ENFORCED scene."""
    import yaml

    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet_core.yaml"' in source
    overlay = yaml.safe_load(
        (LAUNCH.parents[1] / "config" / "map_v2_fleet_core.yaml").read_text(encoding="utf-8"))
    assert overlay["runtime"]["mode"] == "simulation"
    assert overlay["traffic_policy"]["mode"] == "DISABLED"
    assert overlay["traffic_policy"]["map_id"] == "map_v2_fleet"


def test_line_observer_runs_two_line_lane_mode_on_declared_gazebo_ground():
    """The 260919 track bounds each lane with two lines; single-line centroid
    latched onto one boundary in Gazebo. Lane mode needs the metric ground."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("camera_lane_mode", default_value="edge_left")' in source
    assert '"camera_ground_source": "GAZEBO"' in source
    assert '"allow_simulation_ground": True' in source
    assert '"gazebo_camera_height_m": 0.060194' in source
    assert '"gazebo_camera_pitch_rad": math.radians(25.0)' in source
    assert '"gazebo_camera_hfov_rad": 1.1519' in source
    assert '"gazebo_camera_max_range_m": 0.6' in source
    assert '"camera_roi_top_fraction": 0.25' in source
    assert '"camera_roi_bottom_fraction": 0.75' in source
    assert '"use_sim_time": True' in source


def test_crosswalk_paint_is_not_mistaken_for_overexposure():
    """Run 164241: entering the crosswalk lit 48-54% of the lane band, above the
    0.40 washed-out cut, so every frame read as 'no lane' and CORE went LOST.
    A crosswalk is legitimate paint; only a near-white frame is overexposure."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"camera_washed_fraction": 0.75' in source


def test_line_observer_turns_corners_with_the_measured_camera_offset():
    """Run 164757 stopped fail-closed at the first 90 deg corner. The camera
    optical centre is 0.020 + 0.015*cos(25 deg) = 0.034 m ahead of base_link."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"lane_corner_turning": True' in source
    assert '"camera_x_offset_m": 0.034' in source


def test_lap_runs_left_edge_following():
    """Run 184434 stopped where both lines bend 65 deg: the lap holds the inner
    block's outline on the left instead of pairing lines row by row."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("camera_lane_mode", default_value="edge_left")' in source
    assert '"lane_corner_turning": True' in source


def test_launch_exposes_mode_and_spawn_for_the_junction_harness():
    source = LAUNCH.read_text(encoding="utf-8")
    for arg in ('"camera_lane_mode"', '"spawn_x"', '"spawn_y"', '"spawn_yaw"', '"debug_overlay"'):
        assert f"DeclareLaunchArgument({arg}" in source


def test_camera_lane_mode_is_typed_as_a_string_parameter():
    """A bare LaunchConfiguration substitution can be handed to rclpy as a
    non-string ParameterType depending on how the launch frontend resolves
    it; wrap it like debug_overlay's ParameterValue(..., value_type=bool)
    so 'centre'/'edge_left'/'lane' always arrive as a ROS string param."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert ('"camera_lane_mode": ParameterValue(\n'
            '                    LaunchConfiguration("camera_lane_mode"), value_type=str)') in source


def test_route_args_declared_empty_for_the_junction_prototypes():
    """route_a/route_b/route_ab (Task 6). Empty by default so line/lane/
    edge_left/centre are unaffected; the harness overrides them per scenario."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert "route_a/route_b/route_ab only" in source
    assert 'DeclareLaunchArgument("route", default_value="[]")' in source
    assert 'DeclareLaunchArgument("route_start", default_value="[]")' in source
    assert '"lane_graph_path": os.path.join(\n' \
           '                    control_share, "map", "map_v2_fleet", "lane_graph.yaml")' in source


def test_route_and_route_start_are_typed_as_arrays_from_a_yaml_flow_list_string():
    """A launch-arg substitution is always a string; ParameterValue's
    List[str]/List[float] value_type parses a YAML flow-list string (e.g.
    '[west:f, ring_w:f]') into the node's declared string/double array
    parameters, matching what junction_harness.py builds for route_a/route_b."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert ('"route": ParameterValue(\n'
            '                    LaunchConfiguration("route"), value_type=List[str])') in source
    assert ('"route_start": ParameterValue(\n'
            '                    LaunchConfiguration("route_start"), value_type=List[float])'
            ) in source
    assert "from typing import List" in source


def test_the_dock_observer_is_opt_in_with_the_declared_gazebo_camera():
    """Stage 3 (parking): control's dock_observer_node observes the wedge
    tag on the declared Gazebo camera (25 deg, 0.0602 m, 0.0285 m ahead,
    hfov 1.1519), only when dock_observer:=true. It owns no motion."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("dock_observer", default_value="false")' in source
    block = source.split('executable="dock_observer_node"', 1)[1].split("Node(", 1)[0]
    assert "IfCondition(LaunchConfiguration(\"dock_observer\"))" in block
    for text in ['"camera_geometry_source": "GAZEBO"', '"use_sim_time": True',
                 '"camera_height_m": 0.060194', '"camera_pitch_rad": math.radians(25.0)',
                 '"camera_hfov_rad": 1.1519', '"camera_x_offset_m": 0.028481',
                 '"tag_id": 7', '"tag_size_m": 0.05']:
        assert text in block, text
    assert "cmd_vel" not in source


URDF = Path(__file__).resolve().parents[2] / "description" / "urdf" / "rosy.urdf.xacro"


def _urdf_camera_on_base_footprint(tilt_rad):
    """front_camera_link (the Gazebo camera sensor's frame) on base_footprint,
    from the xacro's joint chain: base_footprint -> base_link ->
    front_camera_mount (pitched `tilt_rad`) -> front_camera_link. Returns
    (x ahead, z above the floor)."""
    import math
    import re

    source = URDF.read_text(encoding="utf-8")

    def origin(joint):
        block = re.split(rf'<joint name="(?:\$\{{namespace\}})?{joint}"', source, maxsplit=1)[1]
        block = block.split("</joint>", 1)[0]
        xyz = re.search(r'<origin xyz="([^"]+)"', block).group(1)
        return [float(v) for v in xyz.split()]

    base = origin("base_link_fixed_joint")
    mount = origin("front_camera_mount_fixed_joint")
    link = origin("front_camera_fixed_joint")
    s, c = math.sin(tilt_rad), math.cos(tilt_rad)
    # R_y(tilt) applied to the link offset inside the pitched mount.
    x = base[0] + mount[0] + c * link[0] + s * link[2]
    z = base[2] + mount[2] - s * link[0] + c * link[2]
    return x, z


def test_the_dock_observer_mount_is_the_urdf_camera():
    """The declared mount must be where Gazebo puts the camera. 0.034 was
    0.020 + 0.015*cos(25 deg) and dropped the link's -0.0121 m drop inside
    the pitched mount (-0.0121*sin(25 deg) = -5.1 mm along x): the dock tag
    read 5.5 mm long in every Gazebo frame. gz sdf -p puts the sensor at
    (0.0284809, 0, 0.0601944) on base_footprint."""
    import math
    import re

    x, z = _urdf_camera_on_base_footprint(math.radians(25.0))
    assert (round(x, 6), round(z, 6)) == (0.028481, 0.060194)
    block = LAUNCH.read_text(encoding="utf-8").split(
        'executable="dock_observer_node"', 1)[1].split("Node(", 1)[0]
    declared_x = float(re.search(r'"camera_x_offset_m": ([0-9.]+)', block).group(1))
    declared_z = float(re.search(r'"camera_height_m": ([0-9.]+)', block).group(1))
    assert abs(declared_x - x) < 1e-5
    assert abs(declared_z - z) < 1e-5
