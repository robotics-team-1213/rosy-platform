"""gz_multi core:=true — 로봇별 core 가 서로 다른 포트·HOME·설정으로 뜬다.

런치 파일은 모듈이 아니라 경로로 import 한다. `launch` 가 없는 환경(Windows)은 skip.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import stat
from pathlib import Path

import pytest
import yaml

launch = pytest.importorskip("launch")
# ROS 2 launch 는 처음 import 될 때 logging.setLoggerClass(LaunchLogger) 를 걸어, 이 pytest
# 프로세스에서 그 뒤 만들어지는 로거가 모두 propagate=False 가 된다(다른 시험의 caplog 가 빈다).
logging.setLoggerClass(logging.Logger)
if not hasattr(launch, "LaunchContext"):
    # 여러 시험 디렉터리를 한 번에 돌리면 `src/gz_sim` 가 sys.path 에 얹히고,
    # 그때 `import launch` 는 이 패키지의 `launch/` 디렉터리를 namespace 패키지로
    # 집어온다. importorskip 은 통과하지만 ROS 2 의 launch 가 아니라서 수집이 깨진다.
    pytest.skip("`launch` resolved to this package's launch/ directory, not ROS 2 launch",
                allow_module_level=True)
from launch import LaunchContext  # noqa: E402
from launch.actions import TimerAction  # noqa: E402
from launch_ros.actions import Node, ROSTimer  # noqa: E402

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "gz_multi.launch.py"


def _module():
    spec = importlib.util.spec_from_file_location("gz_multi_launch", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_core_config_sets_identity_and_port():
    mod = _module()
    cfg = mod._core_config("rosy_02", 8081)
    assert cfg["robot"]["id"] == "rosy_02"
    assert cfg["robot"]["name"] == "Rosy 02"
    assert cfg["network"]["api_port"] == 8081
    # 이 코어들은 시뮬이고 유일한 클라이언트는 같은 기계의 fleet 이다. 0.0.0.0 이면
    # 개발용 토큰을 문 API 가 랜에 열린다.
    assert cfg["network"]["api_host"] == "127.0.0.1"


def test_slam_config_keeps_small_track_walls_at_mapping_resolution():
    mod = _module()
    try:
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory("navigation")
    except Exception as exc:
        pytest.skip(f"navigation share missing: {exc}")

    params = mod._slam_config("rosy_01", share)["/**"]["ros__parameters"]

    assert params["resolution"] == pytest.approx(.02)
    assert params["minimum_travel_distance"] <= .10
    # The Gazebo model-pose odometry is exact.  Letting scan matching refine
    # it can choose a wrong repeated-wall alignment and create ghost maps.
    assert params["use_scan_matching"] is False
    assert params["do_loop_closing"] is False


def test_nav_config_applies_reducing_only_narrow_space_trial():
    mod = _module()
    try:
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory("navigation")
    except Exception as exc:
        pytest.skip(f"navigation share missing: {exc}")

    params = mod._nav_config("rosy_01", share)["rosy_01"]
    controller = params["controller_server"]["ros__parameters"]
    follow = controller["FollowPath"]
    smoother = params["velocity_smoother"]["ros__parameters"]

    assert follow["desired_linear_vel"] == pytest.approx(.10)
    assert follow["min_lookahead_dist"] == pytest.approx(.15)
    assert follow["max_lookahead_dist"] == pytest.approx(.30)
    assert follow["use_regulated_linear_velocity_scaling"] is True
    assert follow["use_cost_regulated_linear_velocity_scaling"] is True
    assert follow["cost_scaling_dist"] == pytest.approx(.15)
    assert controller["progress_checker"]["required_movement_radius"] == pytest.approx(.05)
    # D-395 R4: RPP rotates to the goal heading with linear 0 whenever the carrot is
    # nearer than xy_goal_tolerance. The carrot sits about one lookahead ahead, so a
    # tolerance at or above min_lookahead_dist means the robot never drives forward.
    goal_checker = controller["general_goal_checker"]
    assert goal_checker["xy_goal_tolerance"] < follow["min_lookahead_dist"]
    assert smoother["max_velocity"] == pytest.approx([.10, 0., .50])
    assert smoother["min_velocity"] == pytest.approx([-.10, 0., -.50])

    # SmacPlanner2D is orientationless.  Give both costmaps the padded
    # circumscribed radius so a square robot cannot enter a corner that only
    # fits at yaw=0 and then become "start occupied" while turning.
    padded_radius = (2 * .06 ** 2) ** .5 + .03
    global_params = params["global_costmap"]["global_costmap"]["ros__parameters"]
    assert "footprint" not in global_params
    assert global_params["robot_radius"] == pytest.approx(padded_radius)
    assert global_params["footprint_padding"] == pytest.approx(0.)
    # D-395 R4: the local costmap is RPP's collision checker, not the planner's. The
    # padded circle (0.115 m) plus 5 cm cells covers the wall 0.14 m from square A, so
    # RPP reported "collision ahead" before the first move. It keeps the device footprint.
    local_params = params["local_costmap"]["local_costmap"]["ros__parameters"]
    assert local_params["footprint"] == '[[0.06, 0.06], [0.06, -0.06], [-0.06, -0.06], [-0.06, 0.06]]'
    assert "robot_radius" not in local_params
    for costmap_params in (global_params, local_params):
        assert costmap_params["inflation_layer"]["inflation_radius"] == pytest.approx(.15)


def test_robots_manifest_lists_every_core_with_the_dev_operator_token():
    mod = _module()
    rows = mod._robots_manifest(["rosy_01", "rosy_02"], 8080)
    assert rows == [
        {"robot_id": "rosy_01", "base_url": "http://127.0.0.1:8080", "token": "rosy-dev-operator"},
        {"robot_id": "rosy_02", "base_url": "http://127.0.0.1:8081", "token": "rosy-dev-operator"},
    ]


def _setup(mod, **overrides):
    context = LaunchContext()
    context.launch_configurations.update({
        "robots": "3", "prefix": "rosy", "world_name": "rosy_factory.world", "mode": "none",
        "headless": "true", "spawn_spacing": "1.5", "core": "true", "api_port_base": "8080",
        "inflation_radius": "", "spawn_x": "", "spawn_y": "", "map": "", "loc_assist": "true",
        "spawn_poses": "", "seed_initialpose": "true", "nav_composition": "false",
        "physics_step": "", "real_time_factor": "", "gpu": "false",
        **overrides,
    })
    try:
        return mod._launch_setup(context), context
    except Exception as exc:  # ros_gz_sim 등 share 디렉터리가 없는 러너
        if "not found" in str(exc).lower() or "PackageNotFound" in type(exc).__name__:
            pytest.skip(f"package share missing: {exc}")
        raise


def _text(value, context) -> str:
    """launch 는 문자열을 Substitution 목록으로 정규화해 둔다. 어느 형태든 문자열로."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "".join(_text(v, context) for v in value)
    return value.perform(context)


def _core_nodes(actions, context):
    return [a for a in actions
            if isinstance(a, Node) and _text(a.node_package, context) == "core"]


def _env(node, context) -> dict:
    # Node → ExecuteLocal.process_description (launch.descriptions.Executable) .additional_env:
    # [(key_substitutions, value_substitutions), ...]
    return {_text(k, context): _text(v, context) for k, v in (node.process_description.additional_env or [])}


def test_core_true_adds_one_core_per_robot_with_distinct_ports_and_homes():
    mod = _module()
    actions, context = _setup(mod)
    cores = _core_nodes(actions, context)
    assert len(cores) == 3
    envs = [_env(a, context) for a in cores]
    assert [e["ROSY_NAMESPACE"] for e in envs] == ["rosy_01", "rosy_02", "rosy_03"]
    # D-193 7: the dev operator token in robots.yaml exists only with ROSY_DEV_AUTH=1.
    assert all(e["ROSY_DEV_AUTH"] == "1" for e in envs)
    assert len({e["HOME"] for e in envs}) == 3
    ports = []
    for e in envs:
        import yaml
        with open(e["ROSY_CONFIG"], encoding="utf-8") as f:
            ports.append(yaml.safe_load(f)["network"]["api_port"])
    assert ports == [8080, 8081, 8082]
    # robots.yaml 은 설정 파일과 같은 임시 디렉터리에 쓰인다.
    manifest = os.path.join(os.path.dirname(envs[0]["ROSY_CONFIG"]), "robots.yaml")
    assert os.path.exists(manifest)
    if os.name != "nt":
        # robots.yaml 은 운영자 토큰을 담고 있고 /tmp 에 쓰인다. 기본 모드로 두면
        # 그 기계의 누구나 읽는다. (Windows 에는 대응하는 비트가 없다.)
        assert stat.S_IMODE(os.stat(manifest).st_mode) == 0o600


def test_core_false_adds_no_core():
    mod = _module()
    actions, context = _setup(mod, core="false")
    assert not _core_nodes(actions, context)


def test_nominal_camera_keeps_transport_outside_multi_and_renders_headlessly():
    from launch.actions import IncludeLaunchDescription
    mod = _module()
    actions, context = _setup(mod, robots="2", core="false", nominal_camera="true")
    assert '--headless-rendering' in _gz_server_args(actions, context)
    assert _named(actions, context, 'image_bridge') == []
    uploads = []
    for action in actions:
        if isinstance(action, IncludeLaunchDescription):
            location = _text(action.launch_description_source._LaunchDescriptionSource__location, context)
            if location.endswith('upload_robot.launch.py'):
                uploads.append(dict(action.launch_arguments))
    assert len(uploads) == 2
    for args in uploads:
        assert _text(args['camera_width'], context) == '320'
        assert _text(args['camera_height'], context) == '240'
        assert _text(args['cam_tilt_deg'], context) == '8'


def test_two_camera_launch_isolates_observers_and_preview_per_robot(monkeypatch, tmp_path):
    import yaml
    from launch.actions import OpaqueFunction
    spec = importlib.util.spec_from_file_location('multi_real', LAUNCH.parent / 'map_v2_fleet_multi_real.launch.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, 'get_package_share_directory', lambda name: str(LAUNCH.parents[1]))
    actions = mod.generate_launch_description().entities
    context = LaunchContext()
    context.launch_configurations['learned_lane_pointer'] = '/pinned/model-pointer.txt'
    reservations = []
    for index, ns in enumerate(('rosy_01', 'rosy_02')):
        port = 31961 + index
        reservations.append(dict(namespace=ns, api_port=port))
        (tmp_path / f'core_{ns}.yaml').write_text(yaml.safe_dump(dict(
            robot=dict(id=ns), network=dict(api_host='127.0.0.1', api_port=port),
            line_follow=dict(cruise_speed=.08 + .01*index))), encoding='utf-8')
    run_spec = tmp_path / 'run-spec.yaml'
    run_spec.write_text(yaml.safe_dump(dict(run_id='law-test', core_config_dir=str(tmp_path),
        fleet_manifest='robots.yaml', hub_url='http://127.0.0.1', gz_partition='law-test',
        ros_domain_id=89, robots=reservations)), encoding='utf-8')
    context.launch_configurations['run_spec'] = str(run_spec)
    for action in tuple(actions):
        if isinstance(action, OpaqueFunction):
            actions.extend(action.execute(context))
    for executable in ('image_bridge', 'line_observer_node', 'road_observer_node'):
        nodes = _named(actions, context, executable)
        assert len(nodes) == 2
        assert {_text(n._Node__node_namespace, context).strip('/') for n in nodes} == {'rosy_01', 'rosy_02'}
    observers = _named(actions, context, 'line_observer_node')
    assert all('ROSY_CONFIG' not in _env(n, context) for n in observers)
    for index, node in enumerate(observers):
        # The mocked share dir has no control/config/line_follow.yaml, so do not
        # evaluate the yaml parameter. The law dict is already the last element.
        from launch_ros.utilities import evaluate_parameters
        law = evaluate_parameters(context, [node._Node__parameters[-1]])[0]
        assert law['core_cruise_speed'] == pytest.approx(.08+.01*index)
        assert {k for k in law if str(k).startswith('core_')} == {
            'core_cruise_speed', 'core_max_linear', 'core_steering_gain', 'core_min_confidence'}
    assert _named(actions, context, 'sim_jpeg_relay.py') == []  # Road observer owns each front preview.
    assert _named(actions, context, 'core') == []  # COREs belong to the included multi launch.


def test_observer_law_loader_preserves_launch_environment_and_excludes_secrets(tmp_path, monkeypatch):
    import sys
    import yaml
    sys.path.insert(0, str(LAUNCH.parent))
    from gz_multi_parts import observer_steering_law
    overlay = tmp_path/'core.yaml'
    overlay.write_text(yaml.safe_dump(dict(line_follow=dict(cruise_speed=.06, steering_gain=1.7),
        auth=dict(tokens=[dict(token='never-forward-to-camera')]))), encoding='utf-8')
    monkeypatch.setenv('ROSY_CONFIG', '/caller-private.yaml')
    law = observer_steering_law(str(overlay))
    assert law['core_cruise_speed'] == .06 and law['core_steering_gain'] == 1.7
    assert set(law) == {'core_'+key for key in ('cruise_speed','max_linear','steering_gain','min_confidence')}
    assert os.environ['ROSY_CONFIG'] == '/caller-private.yaml'


def test_slam_start_waits_for_sensor_startup_in_wall_time():
    mod = _module()
    actions, _ = _setup(mod, robots="1", core="false", mode="slam")
    timers = [action for action in actions if isinstance(action, TimerAction)]

    assert len(timers) == 1
    assert not isinstance(timers[0], ROSTimer)
    assert timers[0].period == 15.0
    assert timers[0].actions


def _loc_assist_includes(actions, context):
    """D-395 P2-3: the per-robot loc_assist launch rides in the delayed nav actions."""
    from launch.actions import IncludeLaunchDescription
    found = []
    for timer in (a for a in actions if isinstance(a, TimerAction)):
        for action in timer.actions:
            if isinstance(action, IncludeLaunchDescription):
                # Before execution `.location` is str() of the substitutions (an object repr
                # on Jazzy), so read the substitution list and perform it.
                source = action.launch_description_source
                location = _text(source._LaunchDescriptionSource__location, context)
                if location.endswith("loc_assist.launch.py"):
                    found.append(action)
    return found


def test_nav_mode_starts_loc_assist_per_robot_unless_turned_off():
    mod = _module()
    actions, context = _setup(mod, robots="2", core="false", mode="nav")
    assert len(_loc_assist_includes(actions, context)) == 2
    actions, context = _setup(mod, robots="2", core="false", mode="nav", loc_assist="false")
    assert _loc_assist_includes(actions, context) == []


def _named(actions, context, executable):
    return [a for a in actions
            if isinstance(a, Node) and _text(a.node_executable, context) == executable]


def _spawn_pose(node, context):
    # Node.cmd exists only after execute(); the declared arguments are on the action.
    args = [_text(a, context) for a in node._Node__arguments]
    return tuple(float(args[args.index(flag) + 1]) for flag in ("-x", "-y", "-Y"))


def test_spawn_poses_default_keeps_the_catalog_row_at_yaw_zero():
    mod = _module()
    actions, context = _setup(mod, robots="2", core="false")
    poses = [_spawn_pose(n, context) for n in _named(actions, context, "create")]
    assert [p[2] for p in poses] == [0.0, 0.0]
    assert poses[1][0] - poses[0][0] == pytest.approx(1.5)
    assert poses[0][1] == poses[1][1]


def test_spawn_poses_place_each_robot_and_seed_its_yaw():
    """D-395 S1: on-square, off-slot and mirror placements need a pose per robot."""
    mod = _module()
    actions, context = _setup(mod, robots="2", core="false", mode="nav",
                              spawn_poses="-1.26,0.49,1.5708; 0.3,-0.3,3.1416")
    poses = [_spawn_pose(n, context) for n in _named(actions, context, "create")]
    assert poses == [(-1.26, 0.49, 1.5708), (0.3, -0.3, 3.1416)]
    assert len(_named(actions, context, "seed_initialpose.py")) == 2


def test_seed_initialpose_false_leaves_amcl_unseeded():
    mod = _module()
    actions, context = _setup(mod, robots="2", core="false", mode="nav", seed_initialpose="false")
    assert _named(actions, context, "seed_initialpose.py") == []


# --- D-395 S2 rerun: sim-only physics step and GPU rendering --------------------------------
FLEET_WORLD = (LAUNCH.parents[4] / "middleware") / "perception" / "map" / "map_v2_fleet" / "worlds" / "map_v2_fleet.world"
FACTORY_WORLD = LAUNCH.parents[1] / "worlds" / "rosy_factory.world"


def _args_module():
    import sys
    sys.path.insert(0, str(LAUNCH.parent))
    import gz_multi_args
    return gz_multi_args


def _physics(path):
    import xml.etree.ElementTree as ET
    world = ET.parse(path).getroot().find("world")
    return world, world.findall("physics")


def test_physics_step_default_loads_the_world_unchanged(tmp_path):
    args = _args_module()
    assert args.physics_world(str(FLEET_WORLD), None, None, str(tmp_path)) == str(FLEET_WORLD)
    assert list(tmp_path.iterdir()) == []


def test_physics_step_writes_a_world_copy_with_only_the_physics_changed(tmp_path):
    args = _args_module()
    path = args.physics_world(str(FLEET_WORLD), 0.005, None, str(tmp_path))
    assert os.path.dirname(path) == str(tmp_path)
    world, physics = _physics(path)
    assert len(physics) == 1     # map_v2_fleet has none; Gazebo would default to 1 ms
    assert float(physics[0].find("max_step_size").text) == 0.005
    assert float(physics[0].find("real_time_factor").text) == 1.0
    source, _ = _physics(FLEET_WORLD)
    assert world.get("name") == source.get("name")
    for tag in ("plugin", "model", "include", "light"):
        assert len(world.findall(tag)) == len(source.findall(tag))
    assert "model://control/map/map_v2_fleet/meshes/road_lines.stl" in open(path, encoding="utf-8").read()


def test_physics_step_replaces_an_existing_physics_block(tmp_path):
    args = _args_module()
    path = args.physics_world(str(FACTORY_WORLD), 0.004, 2.0, str(tmp_path))
    _, physics = _physics(path)
    assert len(physics) == 1
    assert len(physics[0].findall("max_step_size")) == 1
    assert float(physics[0].find("max_step_size").text) == 0.004
    assert float(physics[0].find("real_time_factor").text) == 2.0


@pytest.mark.parametrize("step,rtf", [(0.02, None), (0., None), (-0.005, None), (0.005, 0.)])
def test_physics_step_rejects_steps_the_imu_cannot_keep_up_with(tmp_path, step, rtf):
    args = _args_module()
    with pytest.raises(ValueError):
        args.physics_world(str(FLEET_WORLD), step, rtf, str(tmp_path))


def _gz_server_args(actions, context):
    from launch.actions import IncludeLaunchDescription
    for action in actions:
        if isinstance(action, IncludeLaunchDescription):
            launch_args = {_text(k, context): _text(v, context) for k, v in action.launch_arguments}
            if " -s " in launch_args.get("gz_args", ""):
                return launch_args["gz_args"]
    raise AssertionError("no gz sim server include")


def _set_env(actions, context):
    from launch.actions import SetEnvironmentVariable
    return {_text(a.name, context): _text(a.value, context)
            for a in actions if isinstance(a, SetEnvironmentVariable)}


def test_validation_domain_is_delivered_before_all_participants(tmp_path):
    import yaml
    from launch.actions import SetEnvironmentVariable, IncludeLaunchDescription
    spec = {"run_id": "d426-test", "core_config_dir": str(tmp_path),
            "fleet_manifest": str(tmp_path / "robots.yaml"), "hub_url": "http://127.0.0.1:32001",
            "gz_partition": "d426-test", "ros_domain_id": 80,
            "robots": [{"namespace": "rosy_01", "api_port": 31001}]}
    (tmp_path / "core_rosy_01.yaml").write_text(yaml.safe_dump({
        "robot": {"id": "rosy_01"}, "network": {"api_host": "127.0.0.1", "api_port": 31001}}),
        encoding="utf-8")
    path = tmp_path / "run_spec.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    actions, context = _setup(_module(), robots="1", run_spec=str(path))
    applied = False
    for action in actions:
        if isinstance(action, SetEnvironmentVariable):
            action.execute(context)
            if _text(action.name, context) == "ROS_DOMAIN_ID":
                applied = True
        elif isinstance(action, (IncludeLaunchDescription, Node, TimerAction)):
            assert applied and context.environment["ROS_DOMAIN_ID"] == "80"
    assert applied and _set_env(actions, context)["GZ_PARTITION"] == "d426-test"
    legacy, context = _setup(_module(), robots="1", core="false")
    assert "ROS_DOMAIN_ID" not in _set_env(legacy, context)


def test_launch_defaults_keep_the_catalog_world_and_the_software_renderer():
    mod = _module()
    actions, context = _setup(mod, robots="1", core="false")
    assert "physics_" not in _gz_server_args(actions, context)
    assert "GALLIUM_DRIVER" not in _set_env(actions, context)
    declared = {a.name: a.default_value for a in mod.generate_launch_description().entities
                if hasattr(a, "default_value")}
    assert _text(declared["physics_step"], context) == ""
    assert _text(declared["real_time_factor"], context) == ""
    assert _text(declared["gpu"], context) == "false"


def test_launch_physics_step_and_gpu_reach_the_gazebo_server():
    mod = _module()
    actions, context = _setup(mod, robots="1", core="false", physics_step="0.005", gpu="true")
    gz_args = _gz_server_args(actions, context)
    world = gz_args.split('"')[1]
    assert os.path.basename(world) == "physics_rosy_factory.world"
    _, physics = _physics(world)
    assert float(physics[0].find("max_step_size").text) == 0.005
    assert _set_env(actions, context)["GALLIUM_DRIVER"] == "d3d12"
    # Set before the server starts: launch runs its actions in order.
    env_at = next(i for i, a in enumerate(actions) if "GALLIUM_DRIVER" in _set_env([a], context))
    server_at = next(i for i, a in enumerate(actions) if _gz_server_args_or_none([a], context))
    assert env_at < server_at


def _gz_server_args_or_none(actions, context):
    try:
        return _gz_server_args(actions, context)
    except AssertionError:
        return None
