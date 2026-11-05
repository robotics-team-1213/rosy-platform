"""Fail-closed contracts for the physical hardware mapping backend (D-144)."""

from pathlib import Path
from xml.etree import ElementTree

import yaml

from robot_contracts import DEPLOY, NAV_LAUNCH, NAV_PARAMS, ROOT, compose


def test_mapping_capability_overlay_advertises_only_an_available_slam_graph():
    path = DEPLOY / "config" / "capabilities.hardware-mapping.yaml"
    caps = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert caps["slam"] is True
    assert caps["teleop"] is True
    assert caps["navigation"]["goal_navigation"] is True
    assert caps["sensors"] == ["lidar", "encoder"]


def test_runtime_wrapper_validates_backend_and_limits_slam_to_hardware():
    script = (DEPLOY / "runtime-mode.sh").read_text(encoding="utf-8")

    assert 'ROSY_NAVIGATION_BACKEND' in script
    assert 'localization|slam' in script
    assert 'slam backend requires hardware runtime mode' in script
    assert 'capabilities.hardware-mapping.yaml' in script
    assert 'ROSY_MAPS_MOUNT_MODE=rw' in script
    assert 'ROSY_MAPS_MOUNT_MODE=ro' in script


def test_compose_passes_backend_and_keeps_write_scope_bounded():
    services = compose()["services"]
    core = services["rosy-core"]
    io = services["rosy-io"]

    assert core["environment"]["ROSY_NAVIGATION_BACKEND"] == (
        "${ROSY_NAVIGATION_BACKEND:-localization}"
    )
    assert core["environment"]["ROSY_MAP_OUTPUT_DIR"] == "/var/lib/rosy/maps"
    assert (
        "./config/${ROSY_CAPABILITIES_FILE:-capabilities.core.yaml}:"
        "/etc/rosy/capabilities.yaml:ro"
    ) in core["volumes"]
    assert "navigation_backend:=${ROSY_NAVIGATION_BACKEND:-localization}" in io["command"]
    assert "${ROSY_DATA_PATH:-/var/lib/rosy}/maps:/var/lib/rosy/maps:${ROSY_MAPS_MOUNT_MODE:-ro}" in io["volumes"]
    assert "${ROSY_DATA_PATH:-/var/lib/rosy}/commissioning:/var/lib/rosy/commissioning:rw" in io["volumes"]
    assert "/var/lib/rosy:/var/lib/rosy:rw" not in io["volumes"]
    health = " ".join(io["healthcheck"]["test"])
    assert "${ROSY_NAVIGATION_BACKEND:-localization}" in health
    assert "slam_toolbox" in health
    assert "amcl" in health
    assert "map_server" in health


def test_io_image_contains_slam_and_bounded_mcap_recording_tools():
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")

    assert "ros-jazzy-slam-toolbox" in dockerfile
    assert "ros-jazzy-ros2bag" in dockerfile
    assert "ros-jazzy-rosbag2-storage-mcap" in dockerfile


def test_hardware_launch_has_mutually_exclusive_localization_and_mapping_graphs():
    launch = (NAV_LAUNCH / "hardware.launch.py").read_text(encoding="utf-8")
    mapping = (NAV_LAUNCH / "mapping_bringup_launch.xml").read_text(encoding="utf-8")

    assert '"navigation_backend"' in launch
    assert "navigation backend must be localization or slam" in launch
    assert "bringup_launch.xml" in launch
    assert "mapping_bringup_launch.xml" in launch
    assert "resolve_occupancy_map" in launch
    assert "map_building.launch.xml" in mapping
    assert "navigation_launch.xml" in mapping
    assert "localization_launch.xml" not in mapping


def test_mapping_scopes_absolute_map_topics_to_robot_namespace():
    mapping = ElementTree.parse(NAV_LAUNCH / "mapping_bringup_launch.xml")
    assert any(
        {
            (remap.attrib["from"], remap.attrib["to"])
            for remap in group.findall("set_remap")
        } >= {("/map", "map"), ("/map_metadata", "map_metadata")}
        and any(
            "map_building.launch.xml" in include.attrib.get("file", "")
            for include in group.findall("include")
        )
        for group in mapping.findall(".//group")
    )


def test_mapper_params_are_rewritten_for_the_robot_namespace(tmp_path):
    import sys

    package = ROOT / "middleware" / "drive" / "planning" / "nav2"
    if str(package) not in sys.path:
        sys.path.append(str(package))
    from navigation.params_rewrite import write_prefixed_nav2_params

    source = package / "params" / "mapper_params.yaml"
    output = Path(write_prefixed_nav2_params(source, "rosy_01", directory=tmp_path))
    params = yaml.safe_load(output.read_text(encoding="utf-8"))["/rosy_01/slam_toolbox"][
        "ros__parameters"
    ]

    assert params["odom_frame"] == "rosy_01/odom"
    assert params["base_frame"] == "rosy_01/base_footprint"
    assert params["map_frame"] == "map"
    assert params["scan_topic"] == "/rosy_01/scan"


def test_rewritten_sections_match_namespaced_nodes(tmp_path):
    """bare 섹션 키는 이름공간 노드에 닿지 않는다 (2026-11-04 geg6 실측).

    `ros2 run ... -r __ns:=/rosy_42 ... --params-file` 로 띈 노드는 FQN 섹션
    (`/rosy_42/slam_toolbox:`)일 때만 값을 받는다. bare `slam_toolbox:` 섹션은
    조용히 무시되어 노드가 기본값(/scan, odom)으로 살아 있다 — 맵은 커지지
    않고, 2026-11-03 문서의 벤치 우회가 필요했던 이유다.
    """
    import sys

    package = ROOT / "middleware" / "drive" / "planning" / "nav2"
    if str(package) not in sys.path:
        sys.path.append(str(package))
    from navigation.params_rewrite import write_prefixed_nav2_params

    for source in (package / "params" / "mapper_params.yaml", NAV_PARAMS):
        rewritten = yaml.safe_load(
            Path(
                write_prefixed_nav2_params(source, "rosy_07", directory=tmp_path)
            ).read_text(encoding="utf-8")
        )
        assert rewritten, source.name
        for key in rewritten:
            assert key == f"/rosy_07/{key.rsplit('/', 1)[-1]}", (source.name, key)

    plain = yaml.safe_load(
        Path(
            write_prefixed_nav2_params(
                package / "params" / "mapper_params.yaml", "", directory=tmp_path
            )
        ).read_text(encoding="utf-8")
    )
    assert set(plain) == {"slam_toolbox"}


def test_navigation_package_declares_slam_runtime_dependency():
    package_xml = (
        ROOT / "middleware" / "drive" / "planning" / "nav2" / "package.xml"
    ).read_text(encoding="utf-8")
    assert "<exec_depend>slam_toolbox</exec_depend>" in package_xml


def test_launch_profile_default_prefers_override_then_operator_then_shipped_mode(tmp_path, monkeypatch):
    """native 기기는 /etc/rosy/profile.yaml 이 없어도 프로파일을 찾는다 (2026-11-03 문서 증상1).

    compose 는 모드별 오버레이를 bind-mount 한다. native payload 는 같은 파일을
    deploy/robot/native/config/ 로 싣고, launch 기본값은 ROSY_PROFILE → 운영자 설치 파일 →
    모드 오버레이 순서로 고른다.
    """
    import sys

    package = ROOT / "middleware" / "drive" / "planning" / "nav2"
    if str(package) not in sys.path:
        sys.path.append(str(package))
    from navigation import profile_source

    assert (
        profile_source.default_profile_path({"ROSY_PROFILE": "/bench/profile.yaml"})
        == "/bench/profile.yaml"
    )
    operator = tmp_path / "profile.yaml"
    operator.write_text("profile: {}\n", encoding="utf-8")
    monkeypatch.setattr(profile_source, "OPERATOR_PROFILE", operator)
    assert profile_source.default_profile_path({}) == str(operator)
    monkeypatch.setattr(profile_source, "OPERATOR_PROFILE", tmp_path / "absent.yaml")
    assert (
        profile_source.default_profile_path({"ROSY_RUNTIME_MODE": "hardware"})
        == "/opt/rosy/current/deploy/robot/native/config/profile.hardware.yaml"
    )
    assert profile_source.default_profile_path({}).endswith("/profile.core.yaml")
    launch = (NAV_LAUNCH / "hardware.launch.py").read_text(encoding="utf-8")
    assert "from navigation.profile_source import default_profile_path" in launch
