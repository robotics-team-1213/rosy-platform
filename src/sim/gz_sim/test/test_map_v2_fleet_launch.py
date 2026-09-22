"""map_v2_fleet lane launch keeps CORE the only final cmd_vel publisher."""

import xml.etree.ElementTree as ET
from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "map_v2_fleet_lane.launch.py"
LAUNCH_SIM = Path(__file__).resolve().parents[1] / "launch" / "launch_sim.launch.xml"


def test_launch_uses_the_catalogued_world_and_spawn():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet", "worlds", "map_v2_fleet.world"' in source
    assert '"spawn_x": "-1.26955"' in source
    assert '"spawn_y": "0.24255"' in source
    assert '"bridge_image": "true"' in source


def test_line_observer_threshold_sits_between_body_and_paint():
    """Gazebo run 20260922T_map_v2_fleet_161132 measured grey levels: floor 109,
    the robot's own body filling the bottom rows 218, lane paint 224-228.
    At 180 the body read as line and the frame was rejected as washed out."""
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"camera_bright_threshold": 220' in source


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
