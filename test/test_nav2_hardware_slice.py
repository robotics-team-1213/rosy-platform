"""Nav2 hardware-slice contracts (D-2, D-4, composition, packaging)."""

import sys
from pathlib import Path

import pytest
import yaml

from robot_contracts import (
    DEPLOY,
    NAV_LAUNCH,
    NAV_PARAMS,
    ROOT,
    board_caps,
    board_profile,
    compose,
    hardware_packages,
)

_PKG = str(ROOT / "src" / "runtime" / "navigation")
if _PKG not in sys.path:
    sys.path.append(_PKG)


def test_hardware_mode_advertises_lidar_and_goal_navigation():
    caps = board_caps("hardware")
    profile = board_profile("hardware")
    io = compose()["services"]["rosy-io"]
    command = io["command"]

    assert caps["teleop"] is True
    assert caps["sensors"] == ["lidar", "encoder"]
    assert caps["navigation"]["goal_navigation"] is True
    assert caps["navigation"]["return_home"] is True
    assert caps["slam"] is False
    assert caps["swarm"] == {"follow": False, "lead": False}
    assert profile["profile"]["sensors"] == [
        {"lidar": "rplidar_c1"},
        {"encoder": "dynamixel"},
    ]
    assert "navigation" in command
    assert "hardware.launch.py" in command
    assert "enable_lidar:=true" in command
    assert "enable_battery:=false" in command
    assert any("ttyAMA0" in device for device in io["devices"])
    assert io["healthcheck"]["start_period"] == "60s"
    assert io["healthcheck"]["timeout"] == "10s"
    health = " ".join(io["healthcheck"]["test"])
    assert "bringup" in health
    assert "lifecycle_manager_navigation" in health
    assert health.count("ros2 node list") == 1


def test_hardware_config_requires_runtime_readiness_evidence():
    config = yaml.safe_load(
        (DEPLOY / "config" / "rosy.pi5.example.yaml").read_text(encoding="utf-8")
    )
    readiness = config["navigation"]["readiness"]

    assert readiness["required"] is True
    assert readiness["stale_after_s"] == 2.0
    assert readiness["required_components"] == [
        "amcl", "map_server", "controller_server", "local_costmap",
        "global_costmap", "motor_adapter",
    ]


def test_core_bridge_subscribes_to_lifecycle_and_motor_readiness_sources():
    bridge = (ROOT / "src" / "runtime" / "core" / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8"
    )
    for topic in (
        '"amcl/transition_event"',
        '"map_server/transition_event"',
        '"controller_server/transition_event"',
        '"local_costmap/local_costmap/transition_event"',
        '"global_costmap/global_costmap/transition_event"',
        '"motor/ready"',
    ):
        assert topic in bridge
    assert "NavigationReadinessGate" in bridge or "_readiness" in bridge


def test_motor_profile_does_not_launch_nav2():
    command = compose()["services"]["rosy-motor"]["command"]

    assert "bringup" in command
    assert "bringup_robot.launch.py" in command
    assert "navigation" not in command
    assert "hardware.launch.py" not in command


def test_io_image_packages_nav2_and_slam_without_aux_drivers():
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY src/runtime/navigation" in dockerfile
    assert "navigation" in dockerfile
    assert "ros-jazzy-navigation2" in dockerfile
    assert "ros-jazzy-nav2-bringup" in dockerfile
    assert "python3-yaml" in dockerfile
    assert "ros-jazzy-slam-toolbox" in dockerfile
    for package in hardware_packages():
        assert package not in dockerfile, package
    assert "!src/runtime/navigation/" in dockerignore


def test_hardware_launch_composes_bringup_and_imports_nav_policy():
    launch = (NAV_LAUNCH / "hardware.launch.py").read_text(encoding="utf-8")

    assert "bringup_robot.launch.py" in launch
    assert "bringup_launch.xml" in launch
    assert "my_map.yaml" in launch
    assert "from navigation.params_rewrite import write_prefixed_nav2_params" in launch
    assert "from navigation.profile_limits import" in launch
    assert "validate_requested_limits" in launch
    assert "DeclareLaunchArgument" in launch
    assert '"profile_file"' in launch
    assert '"allow_demo_map"' in launch
    assert "state_unknown" in launch
    assert "from navigation.site_map import resolve_occupancy_map" in launch
    assert "sys.path.insert" not in launch
    assert "mapping_bringup_launch.xml" in launch
    assert "nav2_web_server" not in launch


def test_hardware_io_mounts_a_host_site_map_directory():
    io = compose()["services"]["rosy-io"]
    motor = compose()["services"]["rosy-motor"]

    assert io["environment"]["ROSY_MAP"] == "${ROSY_MAP:-/var/lib/rosy/maps/site.yaml}"
    assert (
        "${ROSY_DATA_PATH:-/var/lib/rosy}/maps:/var/lib/rosy/maps:"
        "${ROSY_MAPS_MOUNT_MODE:-ro}"
    ) in io["volumes"]
    assert "./config/profile.${ROSY_RUNTIME_MODE:-core}.yaml:/etc/rosy/profile.yaml:ro" in motor[
        "volumes"
    ]
    installer = (DEPLOY / "install-pi.sh").read_text(encoding="utf-8")
    assert '"$ROSY_DATA/maps"' in installer


def test_resolve_occupancy_map_uses_site_yaml_only_when_the_image_exists(tmp_path):
    from navigation.site_map import resolve_occupancy_map

    fallback = tmp_path / "demo.yaml"
    fallback.write_text("image: demo.pgm\n", encoding="utf-8")
    (tmp_path / "demo.pgm").write_bytes(b"P5\n")

    missing = tmp_path / "maps" / "site.yaml"
    assert resolve_occupancy_map(missing, fallback) == str(fallback)

    site = tmp_path / "maps" / "site.yaml"
    site.parent.mkdir()
    site.write_text("image: site.pgm\n", encoding="utf-8")
    assert resolve_occupancy_map(site, fallback) == str(fallback)

    (tmp_path / "maps" / "site.pgm").write_bytes(b"P5\n")
    assert resolve_occupancy_map(site, fallback) == str(site)


def test_resolve_occupancy_map_can_fail_closed_for_field_mode(tmp_path):
    from navigation.site_map import resolve_occupancy_map

    missing = tmp_path / "maps" / "site.yaml"
    fallback = tmp_path / "demo.yaml"
    fallback.write_text("image: demo.pgm\n", encoding="utf-8")

    with pytest.raises(ValueError, match="site occupancy map"):
        resolve_occupancy_map(missing, fallback, allow_fallback=False)


def test_nav2_frame_prefix_module_prefixes_odom_not_map():
    from navigation.frame_prefix import apply_nav2_frame_prefix

    raw = yaml.safe_load(NAV_PARAMS.read_text(encoding="utf-8"))
    prefixed = apply_nav2_frame_prefix(raw, "rosy_01")
    amcl = prefixed["amcl"]["ros__parameters"]
    assert amcl["odom_frame_id"] == "rosy_01/odom"
    assert amcl["base_frame_id"] == "rosy_01/base_footprint"
    assert amcl["global_frame_id"] == "map"
    assert (
        prefixed["bt_navigator"]["ros__parameters"]["robot_base_frame"]
        == "rosy_01/base_link"
    )
    local = prefixed["local_costmap"]["local_costmap"]["ros__parameters"]
    assert local["global_frame"] == "rosy_01/odom"
    assert local["robot_base_frame"] == "rosy_01/base_footprint"
    globmap = prefixed["global_costmap"]["global_costmap"]["ros__parameters"]
    assert globmap["global_frame"] == "map"
    assert globmap["robot_base_frame"] == "rosy_01/base_footprint"
    assert apply_nav2_frame_prefix(raw, "")["amcl"]["ros__parameters"][
        "odom_frame_id"
    ] == "odom"


def test_costmap_observation_topic_is_absolute_so_the_obstacle_layer_hears_the_lidar():
    """실측에서 온 시험 — 상대 토픽은 **코스트맵 노드** 네임스페이스에서 풀린다.

    `topic: scan` 은 `/{ns}/global_costmap/scan` 이 되고, 라이다는 `/{ns}/scan` 에 낸다.
    둘은 만나지 않는다. 장애물 레이어가 관측을 한 번도 못 받으니 nav2 는 정적 맵만 보고
    달렸고, 로봇 두 대가 통로 폭 1.4 m 부터 0.7 m 까지 전부 정면으로 들이받았다(중심 간
    0.01~0.08 m). 플래너는 한 번도 막혔다고 말하지 않았다 - 그쪽에서 통로는 비어 있었다.

    이 결함은 조용하다. 로그도 경고도 남지 않으므로 시험이 아니면 다시 들어온다.
    """
    raw = yaml.safe_load(NAV_PARAMS.read_text(encoding="utf-8"))
    for scope in ("local_costmap", "global_costmap"):
        params = raw[scope][scope]["ros__parameters"]
        layer = params.get("voxel_layer") or params.get("obstacle_layer")
        assert layer["scan"]["topic"].startswith("/"), (
            f"{scope} 의 관측 토픽이 상대 경로다 — 코스트맵 노드 밑으로 풀린다")


def test_the_namespaced_sim_points_the_obstacle_layer_at_that_robots_lidar():
    from navigation.frame_prefix import apply_nav2_frame_prefix

    raw = yaml.safe_load(NAV_PARAMS.read_text(encoding="utf-8"))
    prefixed = apply_nav2_frame_prefix(raw, "rosy_01")

    for scope in ("local_costmap", "global_costmap"):
        params = prefixed[scope][scope]["ros__parameters"]
        layer = params.get("voxel_layer") or params.get("obstacle_layer")
        assert layer["scan"]["topic"] == "/rosy_01/scan"
    # 네임스페이스가 없는 실기는 그대로 /scan 이다.
    plain = apply_nav2_frame_prefix(raw, "")["global_costmap"]["global_costmap"]
    assert plain["ros__parameters"]["obstacle_layer"]["scan"]["topic"] == "/scan"


def test_write_prefixed_nav2_params_writes_a_unique_file(tmp_path):
    from navigation.params_rewrite import write_prefixed_nav2_params

    out = Path(write_prefixed_nav2_params(NAV_PARAMS, "rosy_01", directory=tmp_path))
    assert out.parent == tmp_path
    assert out.name.startswith("rosy_nav2_params_")
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["amcl"]["ros__parameters"]["odom_frame_id"] == "rosy_01/odom"


def test_nav2_composition_loads_into_the_namespaced_container():
    bringup = (NAV_LAUNCH / "bringup_launch.xml").read_text(encoding="utf-8")
    loc = (NAV_LAUNCH / "localization_launch.xml").read_text(encoding="utf-8")
    nav = (NAV_LAUNCH / "navigation_launch.xml").read_text(encoding="utf-8")

    assert "name='$(var container_name)'" in bringup
    assert 'value="$(var namespace)/$(var container_name)"' in bringup
    assert "name='$(var namespace)/$(var container_name)'" not in bringup
    nav_nodes = bringup.split("lifecycle_nodes_nav")[1].split("/>")[0]
    assert "smoother_server" in nav_nodes
    assert 'target="$(var container_name)"' in loc
    assert 'target="$(var container_name)"' in nav


def test_gz_bringup_reuses_robot_nav2_launch():
    gz = (NAV_LAUNCH / "gz_bringup_launch.xml").read_text(encoding="utf-8")

    assert "bringup_launch.xml" in gz
    assert "use_sim_time" in gz
    assert "component_container_isolated" not in gz
    assert "lifecycle_nodes_nav" not in gz


def test_amcl_initial_pose_is_a_pose_dict():
    params = yaml.safe_load(NAV_PARAMS.read_text(encoding="utf-8"))
    pose = params["amcl"]["ros__parameters"]["initial_pose"]
    assert isinstance(pose, dict)
    assert {"x", "y", "yaw"} <= set(pose)


def test_nav2_smoother_output_is_nav_cmd_vel_not_cmd_vel():
    text = (NAV_LAUNCH / "navigation_launch.xml").read_text(encoding="utf-8")

    assert text.count('from="cmd_vel_smoothed" to="nav_cmd_vel"') == 2
    assert 'from="cmd_vel_smoothed" to="cmd_vel"' not in text


def test_hardware_nav2_shares_the_global_tf_bus():
    for name in (
        "bringup_launch.xml",
        "gz_bringup_launch.xml",
        "localization_launch.xml",
        "navigation_launch.xml",
    ):
        text = (NAV_LAUNCH / name).read_text(encoding="utf-8")
        assert '<remap from="/tf" to="tf"/>' not in text, name
        assert '<remap from="/tf_static" to="tf_static"/>' not in text, name
