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
