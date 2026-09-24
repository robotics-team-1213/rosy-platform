"""gz_multi core:=true — 로봇별 core 가 서로 다른 포트·HOME·설정으로 뜬다.

런치 파일은 모듈이 아니라 경로로 import 한다. `launch` 가 없는 환경(Windows)은 skip.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

launch = pytest.importorskip("launch")
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
    assert smoother["max_velocity"] == pytest.approx([.10, 0., .50])
    assert smoother["min_velocity"] == pytest.approx([-.10, 0., -.50])

    # SmacPlanner2D is orientationless.  Give both costmaps the padded
    # circumscribed radius so a square robot cannot enter a corner that only
    # fits at yaw=0 and then become "start occupied" while turning.
    padded_radius = (2 * .06 ** 2) ** .5 + .03
    for costmap in ("local_costmap", "global_costmap"):
        costmap_params = params[costmap][costmap]["ros__parameters"]
        assert "footprint" not in costmap_params
        assert costmap_params["robot_radius"] == pytest.approx(padded_radius)
        assert costmap_params["footprint_padding"] == pytest.approx(0.)
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
        "inflation_radius": "", "spawn_x": "", "spawn_y": "", "map": "",
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
    return {_text(k, context): _text(v, context) for k, v in node.process_description.additional_env}


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


def test_slam_start_waits_for_sensor_startup_in_wall_time():
    mod = _module()
    actions, _ = _setup(mod, robots="1", core="false", mode="slam")
    timers = [action for action in actions if isinstance(action, TimerAction)]

    assert len(timers) == 1
    assert not isinstance(timers[0], ROSTimer)
    assert timers[0].period == 15.0
    assert timers[0].actions
