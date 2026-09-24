"""ROS-free Gazebo sim package surface (D-73). Launch tests stay skippable."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_multi_robot_launch_exist():
    package = (ROOT / "package.xml").read_text(encoding="utf-8")
    assert "<name>gz_sim</name>" in package
    assert "fleet" in package
    launch = (ROOT / "launch" / "gz_multi.launch.py").read_text(encoding="utf-8")
    assert "gz_multi" in launch or "core" in launch
    assert "core" in launch
    assert "spawn_x" in launch
    assert "inflation_radius" in launch
    assert "slam_nav" in launch
    assert launch.count('"use_composition": "False"') >= 2
    assert (ROOT / "config" / "worlds.yaml").is_file()
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "config" in cmake


def test_single_robot_launch_declares_description_runtime_dependency():
    """The installed launch must bring every package it resolves at runtime."""
    package = (ROOT / "package.xml").read_text(encoding="utf-8")
    launch = (ROOT / "launch" / "launch_sim.launch.xml").read_text(
        encoding="utf-8")

    assert "$(find-pkg-share description)" in launch
    assert "<exec_depend>description</exec_depend>" in package


def test_single_robot_gazebo_gui_is_optional():
    """Headless sensor validation must not require a Gazebo GUI process."""
    launch = (ROOT / "launch" / "launch_sim.launch.xml").read_text(
        encoding="utf-8")

    assert '<arg name="gui" default="true"/>' in launch
    assert 'if="$(var gui)"' in launch


def test_single_robot_camera_render_profile_reaches_the_description():
    launch = (ROOT / "launch" / "launch_sim.launch.xml").read_text(
        encoding="utf-8")

    for name, default in (
        ("camera_width", "1280"),
        ("camera_height", "720"),
        ("camera_update_rate", "10"),
    ):
        assert f'<arg name="{name}" default="{default}"/>' in launch
        assert f"<arg name='{name}' value='$(var {name})'/>" in launch


def test_single_robot_spawn_pose_is_tunable_with_existing_defaults():
    launch = (ROOT / "launch" / "launch_sim.launch.xml").read_text(
        encoding="utf-8")

    for name, default, option in (
        ("spawn_x", "0.0", "x"),
        ("spawn_y", "0.0", "y"),
        ("spawn_z", "0.1", "z"),
        ("spawn_yaw", "0.0", "Y"),
    ):
        assert f'<arg name="{name}" default="{default}"/>' in launch
        assert f'-{option} $(var {name})' in launch


def test_semantic_road_uses_a_bounded_camera_profile_and_gazebo_range():
    launch = (ROOT / "launch" / "semantic_road_dashboard.launch.py").read_text(
        encoding="utf-8")

    assert 'DeclareLaunchArgument("camera_width", default_value="320")' in launch
    assert 'DeclareLaunchArgument("camera_height", default_value="180")' in launch
    assert 'DeclareLaunchArgument("camera_update_rate", default_value="5")' in launch
    assert '"camera_width": LaunchConfiguration("camera_width")' in launch
    assert '"camera_height": LaunchConfiguration("camera_height")' in launch
    assert '"camera_update_rate": LaunchConfiguration(' in launch
    assert '"camera_ground_mode": "gazebo_pinhole"' in launch
    assert '"gazebo_camera_height_m": 0.060194' in launch
    assert '"gazebo_camera_pitch_rad": math.radians(25.0)' in launch
    assert '"gazebo_camera_hfov_rad": 1.1519' in launch
    assert '"allow_simulation_ground": True' in launch
    assert '"camera_bright_threshold": 220' in launch
    assert '"bright_threshold": 220' in launch
    assert '"spawn_x": "-0.20"' in launch
    assert '"spawn_y": "-0.15"' in launch

    core = (ROOT / "config" / "semantic_road_core.yaml").read_text(
        encoding="utf-8")
    assert "mode: ENFORCED" in core


def test_actual_semantic_runtime_evidence_is_pose_checked_and_enforced():
    evidence_path = (
        ROOT.parents[2]
        / "docs"
        / "validation"
        / "semantic-road-2026-09-21"
        / "gazebo_runtime_result.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    stopped = evidence["semantic_pose_validation"]["stopped"]
    control = evidence["enforced_control_readback"]

    assert stopped["absolute_error_m"] < 0.01
    assert control["traffic_policy_mode"] == "ENFORCED"
    assert control["candidate_linear_mps"] > 0.0
    assert control["final_linear_velocity_mps"] == 0.0
    assert evidence["gates"]["actual_camera_signal_detection"].startswith(
        "HOLD_")


def test_integrated_acceptance_is_sequential_and_uses_measured_geometry():
    launch = (
        ROOT / "launch" / "pinky_integrated_acceptance.launch.py"
    ).read_text(encoding="utf-8")
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    package = (ROOT / "package.xml").read_text(encoding="utf-8")

    assert "semantic_road_dashboard.launch.py" in launch
    assert "map_260905_update_v2" in launch
    assert "wall_geometry.json" in launch
    assert '"robot_radius": 0.086' in launch
    assert '"footprint_padding": 0.010' in launch
    assert '"start_route_index": 0' in launch
    assert '"exit_on_complete": True' in launch
    assert "OnProcessExit" in launch
    assert "target_action=mapping_runner" in launch
    assert "navigation_launch.xml" in launch
    assert "pinky_nav2_probe.py" in launch
    assert "pinky_acceptance.py" in launch
    assert (ROOT / "launch" / "pinky_integrated_acceptance.launch.py").is_file()
    assert "DIRECTORY" in cmake and "launch" in cmake
    assert "<exec_depend>navigation</exec_depend>" in package


def test_gz_multi_uses_ros_gz_bridge_not_domain_bridge():
    """D-114: 시뮬은 네임스페이스 + ros_gz_bridge. domain_bridge / ROS_DOMAIN_ID 없음."""
    launch = (ROOT / "launch" / "gz_multi.launch.py").read_text(encoding="utf-8")
    assert "ros_gz_bridge" in launch
    assert "parameter_bridge" in launch
    assert "domain_bridge" not in launch
    assert "ROS_DOMAIN_ID" not in launch
    assert "rosy_env.sh" not in launch


def test_gz_multi_seeds_map_initialpose_at_spawn():
    """D-115: nav 모드에서 spawn 좌표를 {ns}/initialpose 로 심는다."""
    launch = (ROOT / "launch" / "gz_multi.launch.py").read_text(encoding="utf-8")
    assert "seed_initialpose" in launch
    assert "spawn_xy" in launch
    script = ROOT / "scripts" / "seed_initialpose.py"
    assert script.is_file()
    raw = script.read_bytes()
    assert raw.startswith(b"#!/usr/bin/env python3\n")
    assert b"\r\n" not in raw
    text = script.read_text(encoding="utf-8")
    assert "initialpose" in text
    assert "get_subscription_count" in text
    assert "while rclpy.ok() and not node.done" in text
    assert "import core" not in text
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "scripts/seed_initialpose.py" in cmake


def test_non_composed_nav2_does_not_apply_namespace_twice():
    """The parent owns the namespace; child launch groups must receive an empty one."""
    bringup = (
        ROOT.parents[1]
        / "navigation"
        / "navigation"
        / "launch"
        / "bringup_launch.xml"
    ).read_text(encoding="utf-8")
    assert bringup.count('<arg name="namespace" value=""/>') == 2


def test_junction_tools_are_installed():
    from pathlib import Path
    cmake = (Path(__file__).resolve().parents[1] / "CMakeLists.txt").read_text(encoding="utf-8")
    for script in ("scripts/record_debug.py", "scripts/junction_score.py",
                   "scripts/junction_harness.py"):
        assert script in cmake


def test_world_to_map_is_installed_and_bench_worlds_exist():
    """HOST에서 도는 정답 맵 생성기가 패키지 표면이다. launch skip이 SOURCE가 아니다."""
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "scripts/world_to_map.py" in cmake
    assert (ROOT / "scripts" / "world_to_map.py").is_file()
    assert (ROOT / "worlds" / "rosy_swarm_bench.world").is_file()
    assert (ROOT / "worlds" / "rosy_maze.world").is_file()
