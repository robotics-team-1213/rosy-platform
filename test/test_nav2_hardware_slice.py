"""Nav2 hardware-slice contracts (D-2, D-4, composition, packaging)."""

import sys
from xml.etree import ElementTree
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

_PKG = str(ROOT / "middleware" / "drive" / "planning" / "nav2")
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
    bridge = (ROOT / "middleware" / "core" / "gateway" / "core" / "bridge" / "ros_bridge.py").read_text(
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

    assert "COPY middleware/drive/planning/nav2" in dockerfile
    assert "navigation" in dockerfile
    assert "ros-jazzy-navigation2" in dockerfile
    assert "ros-jazzy-nav2-bringup" in dockerfile
    assert "python3-yaml" in dockerfile
    assert "ros-jazzy-slam-toolbox" in dockerfile
    for package in hardware_packages():
        assert package not in dockerfile, package
    assert "!middleware/drive/planning/nav2/" in dockerignore


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


def test_localization_hardware_defers_only_navigation_lifecycle():
    hardware = (NAV_LAUNCH / "hardware.launch.py").read_text(encoding="utf-8")
    localization, slam = hardware.split('launch_file = "mapping_bringup_launch.xml"', 1)
    assert '"navigation_autostart": "False"' in localization
    assert '"navigation_autostart": "False"' not in slam
    assert 'executable="start_after_tf"' in hardware
    root = ElementTree.parse(NAV_LAUNCH / "bringup_launch.xml")
    assert root.find("./arg[@name='navigation_autostart']").get("default") == "$(var autostart)"
    for launch_file, expected in (("localization_launch.xml", "$(var autostart)"),
                                  ("navigation_launch.xml", "$(var navigation_autostart)")):
        include = next(node for node in root.findall(".//include") if node.get("file").endswith(launch_file))
        assert include.find("arg[@name='autostart']").get("value") == expected


def test_navigation_startup_waits_for_both_costmaps_and_manager():
    from unittest.mock import Mock

    from navigation.start_after_tf import request_startup

    buffer = Mock()
    client = Mock()
    request, latest = object(), object()
    frames = [("map", "rosy_09/base_footprint"), ("rosy_09/odom", "rosy_09/base_footprint")]
    client.service_is_ready.return_value = False
    assert request_startup(buffer, client, request, frames, latest) is None
    client.service_is_ready.return_value = True
    buffer.can_transform.side_effect = [True, False]
    assert request_startup(buffer, client, request, frames, latest) is None
    client.call_async.assert_not_called()
    buffer.can_transform.side_effect = [True, True]
    assert request_startup(buffer, client, request, frames, latest) is client.call_async.return_value
    client.call_async.assert_called_once_with(request)


@pytest.mark.parametrize("namespace", ["", "rosy_09"])
def test_startup_frames_match_hardware_costmap_parameters(tmp_path, namespace):
    from navigation.params_rewrite import write_prefixed_nav2_params
    from navigation.start_after_tf import costmap_frames

    params = write_prefixed_nav2_params(NAV_PARAMS / "nav2_params.yaml", namespace, directory=tmp_path)
    prefix = f"{namespace}/" if namespace else ""
    assert costmap_frames(params, f"/{namespace}") == [
        ("map", prefix + "base_footprint"),
        (prefix + "odom", prefix + "base_footprint"),
    ]


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
    assert data["/rosy_01/amcl"]["ros__parameters"]["odom_frame_id"] == "rosy_01/odom"


def test_hardware_launch_runs_nav2_standalone_not_composed():
    """합성 로드는 이 Jazzy 빌드에서 조용히 죽는다 (2026-11-03 문서).

    load_composable_node 항목이 건너뛰기거나 이름공간을 잃어서, 합성 경로로는
    Nav2 노드가 device 에 아예 뜨지 않았다. hardware.launch.py 는 device 검증이
    끝난 standalone 경로(use_composition False)만 골라야 한다.
    """
    launch = (
        NAV_LAUNCH / "hardware.launch.py"
    ).read_text(encoding="utf-8")

    assert launch.count('"use_composition": "False"') == 2
    assert '"use_composition": "True"' not in launch


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


def test_hardware_launch_executes_without_name_error_and_gates_loc_assist_to_localization(
    monkeypatch, tmp_path
):
    import importlib.util
    import tempfile
    import types

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    class _LaunchCfg:
        def __init__(self, name):
            self.name = name

        def perform(self, ctx):
            return ctx[self.name]

    class _IfCond:
        def __init__(self, predicate):
            self.predicate = predicate

    class _Source:
        def __init__(self, path):
            self.path = path

    class _DeclareArg:
        def __init__(self, name, *args, **kwargs):
            self.name = name
            self.default_value = kwargs.get("default_value")

    class _Include:
        def __init__(self, source, launch_arguments=None, condition=None, **kwargs):
            self.source = source
            self.launch_arguments = dict(launch_arguments or ())
            self.condition = condition

    class _Opaque:
        def __init__(self, *, function, **kwargs):
            self.function = function

    class _LaunchDesc:
        def __init__(self, entities):
            self.entities = list(entities)

    ament = types.ModuleType("ament_index_python")
    ament_pkgs = types.ModuleType("ament_index_python.packages")
    shares = {
        "navigation": str(ROOT / "middleware" / "drive" / "planning" / "nav2"),
        "bringup": str(tmp_path / "bringup"),
        "control": str(tmp_path / "control"),
    }
    ament_pkgs.get_package_share_directory = shares.__getitem__

    launch = types.ModuleType("launch")
    launch.LaunchDescription = _LaunchDesc
    launch_actions = types.ModuleType("launch.actions")
    launch_actions.DeclareLaunchArgument = _DeclareArg
    launch_actions.IncludeLaunchDescription = _Include
    launch_actions.OpaqueFunction = _Opaque
    launch_conds = types.ModuleType("launch.conditions")
    launch_conds.IfCondition = _IfCond
    launch_srcs = types.ModuleType("launch.launch_description_sources")
    launch_srcs.AnyLaunchDescriptionSource = _Source
    launch_srcs.PythonLaunchDescriptionSource = _Source
    launch_subs = types.ModuleType("launch.substitutions")
    launch_subs.LaunchConfiguration = _LaunchCfg

    for name, mod in {
        "ament_index_python": ament,
        "ament_index_python.packages": ament_pkgs,
        "launch": launch,
        "launch.actions": launch_actions,
        "launch.conditions": launch_conds,
        "launch.launch_description_sources": launch_srcs,
        "launch.substitutions": launch_subs,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    pkg_dir = ROOT / "middleware" / "drive" / "planning" / "nav2"
    monkeypatch.syspath_prepend(str(pkg_dir))
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "profile:\n  max_linear_velocity: 2.0\n  max_angular_velocity: 5.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROSY_PROFILE", str(profile))

    (tmp_path / "site.pgm").write_bytes(b"P5\n2 2\n255\n" + bytes([254, 254, 254, 254]))
    site_yaml = tmp_path / "site.yaml"
    site_yaml.write_text(
        "image: site.pgm\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
        encoding="utf-8",
    )

    spec = importlib.util.spec_from_file_location(
        "_test_hardware_launch", NAV_LAUNCH / "hardware.launch.py"
    )
    assert spec and spec.loader
    hw = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, hw)
    spec.loader.exec_module(hw)

    ld = hw.generate_launch_description()
    declared = {
        e.name: e.default_value for e in ld.entities if isinstance(e, _DeclareArg)
    }
    assert declared["enable_loc_assist"] == "true"

    base_ctx = {
        "namespace": "pinky1",
        "params_file": str(NAV_PARAMS),
        "profile_file": str(profile),
        "footprint_profile_file": "",
        "footprint_state": "unknown",
        "require_measured_footprint": "false",
        "max_linear_mps": "0.20",
        "max_angular_rps": "0.80",
        "use_sim_time": "false",
        "allow_demo_map": "false",
        "map": str(site_yaml),
        "mapper_params_file": str(pkg_dir / "params" / "mapper_params.yaml"),
    }
    loc_actions = hw._include_nav2({**base_ctx, "navigation_backend": "localization"})
    assert [Path(a.source.path).name for a in loc_actions] == [
        "bringup_launch.xml",
        "loc_assist.launch.py",
    ]
    assert isinstance(loc_actions[1].condition, _IfCond)
    assert loc_actions[1].condition.predicate.name == "enable_loc_assist"

    slam_actions = hw._include_nav2({**base_ctx, "navigation_backend": "slam"})
    assert [Path(a.source.path).name for a in slam_actions] == [
        "mapping_bringup_launch.xml",
    ]


def test_map_bundle_occupancy_grid_id_matches_core_features(monkeypatch, tmp_path):
    import importlib.util

    monkeypatch.syspath_prepend(str(ROOT / "middleware" / "core" / "services"))
    from core_features.maps import GridFrame, occupancy_map_id

    spec = importlib.util.spec_from_file_location(
        "_test_map_bundle", ROOT / "middleware" / "perception" / "map" / "map_bundle.py"
    )
    assert spec and spec.loader
    mb = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mb)
    spec.loader.exec_module(mb)

    pixels = bytearray()
    data = []
    for r in range(6):
        for c in range(6):
            occ = r in (0, 5) or c in (0, 5)
            pixels.append(0 if occ else 254)
            data.append(100 if occ else 0)
    (tmp_path / "site.pgm").write_bytes(b"P5\n6 6\n255\n" + bytes(pixels))
    site_yaml = tmp_path / "site.yaml"
    site_yaml.write_text(
        "image: site.pgm\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
        encoding="utf-8",
    )

    frame = GridFrame.from_dict(
        {
            "width": 6,
            "height": 6,
            "resolution": 0.05,
            "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "data": data,
        }
    )
    assert mb.occupancy_grid_id(site_yaml) == occupancy_map_id(frame.to_dict())
