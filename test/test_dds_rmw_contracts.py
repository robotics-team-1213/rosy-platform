"""CycloneDDS, image path, sensor QoS, and Jazzy discovery (D-117–D-120)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_robot_and_dev_envs_pin_cyclonedds():
    """D-117: FastDDS 이중 프로파일이 없다."""
    compose = (ROOT / "deploy" / "robot" / "compose.yaml").read_text(encoding="utf-8")
    env_sh = (ROOT / "env.sh").read_text(encoding="utf-8")
    rosy_env = (
        ROOT / "src" / "devices" / "bringup" / "scripts" / "rosy_env.sh"
    ).read_text(encoding="utf-8")
    dockerfile = (ROOT / "deploy" / "robot" / "Dockerfile").read_text(encoding="utf-8")
    assert "RMW_IMPLEMENTATION: rmw_cyclonedds_cpp" in compose
    assert "rmw_cyclonedds_cpp" in env_sh
    assert "rmw_cyclonedds_cpp" in rosy_env
    assert "ros-jazzy-rmw-cyclonedds-cpp" in dockerfile
    assert "rmw_fastrtps_cpp" not in compose
    assert "rmw_fastrtps_cpp" not in env_sh


def test_gz_multi_pins_cyclone_and_localhost_discovery():
    """D-117 / D-120: 시뮬도 Cyclone. ROS_LOCALHOST_ONLY 는 쓰지 않는다."""
    launch = (
        ROOT / "src" / "sim" / "gz_sim" / "launch" / "gz_multi.launch.py"
    ).read_text(encoding="utf-8")
    assert "rmw_cyclonedds_cpp" in launch
    assert "ROS_AUTOMATIC_DISCOVERY_RANGE" in launch
    assert "LOCALHOST" in launch
    assert "ROS_LOCALHOST_ONLY" not in launch  # Jazzy deprecated; do not set it


def test_env_sh_sets_localhost_discovery_range():
    """D-120: 개발 env.sh 는 LOCALHOST 범위. ROS_LOCALHOST_ONLY 를 켜지 않는다."""
    env_sh = (ROOT / "env.sh").read_text(encoding="utf-8")
    assert "ROS_AUTOMATIC_DISCOVERY_RANGE" in env_sh
    assert "LOCALHOST" in env_sh
    assert "export ROS_LOCALHOST_ONLY" not in env_sh


def test_gz_bridges_do_not_carry_raw_images():
    """D-118: 생 Image 는 parameter_bridge / 기본 image_bridge 에 없다."""
    template = (
        ROOT / "src" / "sim" / "gz_sim" / "launch" / "gz_multi.launch.py"
    ).read_text(encoding="utf-8")
    yaml_bridge = (
        ROOT / "src" / "sim" / "gz_sim" / "params" / "rosy_bridge.yaml"
    ).read_text(encoding="utf-8")
    single = (
        ROOT / "src" / "sim" / "gz_sim" / "launch" / "launch_sim.launch.xml"
    ).read_text(encoding="utf-8")
    assert "sensor_msgs/msg/Image" not in template
    assert "image_bridge" not in template
    assert "sensor_msgs/msg/Image" not in yaml_bridge
    assert "bridge_image" in single
    assert single.count("ros_gz_image") == 1
    assert 'from="/camera/image_raw" to="camera/front"' in single


def test_fleet_and_games_do_not_import_sensor_image():
    """D-118: 관제·게임 호스트는 Image 를 import 하지 않는다."""
    games = ROOT / "src" / "site" / "games" / "games"
    fleet = ROOT / "src" / "site" / "fleet" / "fleet"
    for folder in (games, fleet):
        for path in folder.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "sensor_msgs.msg" not in text or "Image" not in text, path
            assert "from sensor_msgs.msg import Image" not in text, path


def test_scan_image_imu_use_sensor_data_qos():
    """D-119: 생산 LaserScan/Imu/Image pub·sub 은 qos_profile_sensor_data."""
    camera = (
        ROOT / "src" / "core" / "control" / "control" / "camera_detect_node.py"
    ).read_text(encoding="utf-8")
    assert "qos_profile_sensor_data" in camera
    assert "create_publisher(Image, 'camera/front', qos_profile_sensor_data)" in camera
    bridge = (
        ROOT / "src" / "core" / "core" / "core" / "bridge" / "ros_bridge.py"
    ).read_text(encoding="utf-8")
    assert "qos_profile_sensor_data" in bridge
    assert 'create_subscription(LaserScan, "scan", self._on_scan, qos_profile_sensor_data)' in bridge
    assert 'create_subscription(Imu, "imu_raw", self._on_imu, qos_profile_sensor_data)' in bridge
