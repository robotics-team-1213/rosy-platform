"""map_v2_fleet real-profile launch (D-364 5): the Gazebo camera is the Pinky one."""

import ast
import math
from pathlib import Path

import yaml

from test_map_v2_fleet_launch import _urdf_camera_on_base_footprint

ROOT = (Path(__file__).resolve().parents[4] / "src")
LAUNCH = ROOT.parent / "integrations" / "simulation" / "gazebo" / "launch" / "map_v2_fleet_real.launch.py"
NOMINAL = ROOT.parent / "middleware" / "devices" / "pinky" / "profile" / "config" / "camera_nominal.yaml"
BUNDLE = ROOT.parent / "middleware" / "perception" / "map" / "map_v2_fleet"


def test_two_learned_observers_publish_crosswalk_uncertainty():
    tree = ast.parse((LAUNCH.parent / 'map_v2_fleet_multi_real.launch.py').read_text())
    observers = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_observers')
    loop = next(n for n in observers.body if isinstance(n, ast.For))
    assert ast.literal_eval(loop.iter) == ('rosy_01', 'rosy_02')
    nodes = [n for n in ast.walk(loop) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'Node']
    line = next(n for n in nodes if any(k.arg == 'executable' and k.value.value == 'line_observer_node'
                                       for k in n.keywords))
    params = next(k.value.elts[1] for k in line.keywords if k.arg == 'parameters')
    constants = {key.value: value.value for key, value in zip(params.keys, params.values)
                 if isinstance(value, ast.Constant)}
    assert constants.get('crosswalk_uncertainty_enabled') is True
    assert constants['camera_ground_source'] == 'GAZEBO'
    assert constants['allow_simulation_ground'] is True and constants['use_sim_time'] is True


def test_two_camera_road_evidence_matches_core_binding_and_has_one_preview_owner():
    path = LAUNCH.parent / 'map_v2_fleet_multi_real.launch.py'
    calls = [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'Node']
    executables = [next(k.value.value for k in n.keywords if k.arg == 'executable') for n in calls]
    assert executables.count('road_observer_node') == 1  # Instantiated inside the two-namespace loop.
    assert 'sim_jpeg_relay.py' not in executables
    road = calls[executables.index('road_observer_node')]
    params = ast.literal_eval(next(k.value.elts[1] for k in road.keywords if k.arg == 'parameters'))
    core = yaml.safe_load((LAUNCH.parents[1] / 'config/map_v2_fleet_core.yaml').read_text())['traffic_policy']
    assert (params['map_id'], params['scene_revision']) == (core['map_id'], core['scene_revision'])
    assert params['camera_ground_mode'] == 'gazebo_pinhole' and params['allow_simulation_ground'] is True
    assert params['rotate_deg'] == 0 and params['require_camera_controls_stable'] is False
    assert params['gazebo_camera_height_m'] == .06343
    assert params['gazebo_camera_pitch_rad'] == .13962634015954636
    assert params['gazebo_camera_hfov_rad'] == 1.0334
    from control.sensing.perception.camera_ground import simulation_ground_plane
    assert simulation_ground_plane(
        source=params['dashboard_source'],
        simulation_enabled=params['allow_simulation_ground'], use_sim_time=params['use_sim_time'],
        width_px=320, height_px=240, height_m=params['gazebo_camera_height_m'],
        pitch_rad=params['gazebo_camera_pitch_rad'], hfov_rad=params['gazebo_camera_hfov_rad'],
        max_range_m=params['gazebo_camera_max_range_m']) is not None


def _constants():
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id.startswith("REAL_"):
            names[node.targets[0].id] = eval(  # noqa: S307 - literal math only
                compile(ast.Expression(node.value), "launch", "eval"), {"math": math})
    return names


def test_camera_matches_the_nominal_pinky_profile():
    c = _constants()
    nominal = yaml.safe_load(NOMINAL.read_text(encoding="utf-8"))
    fx = nominal["width"] / 2.0 / math.tan(c["REAL_HFOV_RAD"] / 2.0)
    assert abs(fx - nominal["fx"]) < 0.1
    assert abs(math.radians(c["REAL_TILT_DEG"]) - nominal["pitch_rad"]) < 1e-3
    assert c["REAL_CAMERA_HEIGHT_M"] == nominal["height_m"]
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"camera_width": "320"' in source
    assert '"camera_height": "240"' in source


def test_declared_ground_is_where_the_urdf_puts_the_sensor():
    c = _constants()
    x, z = _urdf_camera_on_base_footprint(
        math.radians(c["REAL_TILT_DEG"]), c["REAL_CAM_MOUNT_Z"])
    assert abs(z - c["REAL_CAMERA_HEIGHT_M"]) < 1e-4
    assert abs(x - c["REAL_CAMERA_X_OFFSET_M"]) < 1e-4


def test_launch_uses_the_real_world_and_only_core_commands_motion():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet_real.world"' in source
    assert (BUNDLE / "worlds" / "map_v2_fleet_real.world").is_file()
    assert (BUNDLE / "textures" / "carpet_grey.png").is_file()
    assert '"camera_ground_source": "GAZEBO"' in source
    assert 'DeclareLaunchArgument("camera_lane_mode", default_value="edge_left")' in source
    assert 'executable="core"' in source
    assert "cmd_vel" not in source


def test_default_camera_args_keep_the_lap_bench_camera():
    sim = (ROOT.parent / "integrations" / "simulation" / "gazebo" / "launch" / "launch_sim.launch.xml").read_text(encoding="utf-8")
    assert '<arg name="camera_hfov" default="1.1519"/>' in sim
    assert '<arg name="cam_mount_z" default="0.0495"/>' in sim


def test_training_variant_selects_world_and_graph_from_the_same_bundle():
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "generate_launch_description")
    assignments = {n.targets[0].id: n.value for n in function.body if isinstance(n, ast.Assign)}
    for name in ("world", "map_graph"):
        assert isinstance(assignments[name].args[0].elts[0], ast.Name)
        assert assignments[name].args[0].elts[0].id == "map_bundle"
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'LaunchConfiguration("map_variant")' in source
    assert 'choices=[".", "training-curved"]' in source
    assert '"debug_lane_graph": map_graph' in source
    assert '"lane_graph_path": map_graph' in source
    assert (BUNDLE / "training-curved" / "lane_graph.yaml").is_file()
    assert (BUNDLE / "training-curved" / "worlds" / "map_v2_fleet_real.world").is_file()


def test_acceptance_lap_runs_the_payload_corner_and_offset_values():
    """D-495 SIM acceptance: the payload line_follow.yaml decides corner turning and the lens
    offset; this launch must not pin them, and the payload matches this profile."""
    c = _constants()
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"lane_corner_turning":' not in source and '"camera_x_offset_m":' not in source
    payload = yaml.safe_load((ROOT.parent / "middleware" / "perception" / "config" / "line_follow.yaml").read_text(encoding="utf-8"))
    params = payload["/**/line_observer_node"]["ros__parameters"]
    assert params["lane_corner_turning"] is True
    assert abs(params["camera_x_offset_m"] - c["REAL_CAMERA_X_OFFSET_M"]) < 1e-6
