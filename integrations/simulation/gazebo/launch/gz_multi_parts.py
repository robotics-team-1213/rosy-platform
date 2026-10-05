"""gz_multi_parts.py — gz_multi.launch.py 의 비-launch 부품(순수 함수).

launch 디렉터리의 다른 헬퍼(gz_multi_args·world_profiles)와 같은 방식으로
gz_multi.launch.py 의 sys.path 부트스트랩이 import 한다:

- per-robot ros_gz bridge 매핑(브리지 설정 생성)
- 로봇별 CORE 설정 오버라이드·robots.yaml manifest (레거시 자체 생성 경로)
- D-426 T1 검증 runner 소유 run_spec 읽기

예약(port·domain·partition·토큰)을 여기서 만들지 않는다 — 검증 경로에서 그것은
runner·preflight(tools/validation/fleet_gazebo)의 소유다.
"""

import os

import yaml

#: 시뮬 로봇의 API 토큰. core_common 의 개발 토큰(`config/rosy_dev_auth.yaml`)이다. D-193 7 이후
#: 기본값에는 토큰이 없으므로 core 노드는 `ROSY_DEV_AUTH=1` 로 띄운다.
SIM_OPERATOR_TOKEN = "rosy-dev-operator"


def core_config(ns: str, api_port: int) -> dict:
    """로봇별 core 오버라이드(ROSY_CONFIG). 기본 설정 위에 병합된다.

    frame_prefix 는 ROSY_NAMESPACE 환경변수가 넣으므로 여기 두지 않는다. capabilities 는
    기본 파일이 이미 swarm.follow/lead: true 라 그대로 쓴다.

    api_host 는 루프백이다. 이 코어들은 시뮬이고 유일한 클라이언트인 fleet 은 같은
    기계에서 돈다 — 0.0.0.0 이면 개발 토큰이 붙은 N 대의 API 가 로컬 네트워크에 열린다.
    """
    number = ns.rsplit("_", 1)[-1]
    return {
        "robot": {"id": ns, "name": f"Rosy {number}"},
        "network": {"api_host": "127.0.0.1", "api_port": api_port},
        # 시뮬은 조속 프리셋(low/mid/high)이 의미 있도록 상한을 연다.
        # 실기 상한은 장치 프로필/호스트 설정이 그대로 적용된다(여기는 영향 없음).
        "max_linear": 0.6,
        "max_angular": 2.0,
    }


def robots_manifest(namespaces: list, api_port_base: int) -> list:
    """fleet CLI 가 읽는 robots.yaml 의 `robots` 목록(레거시 경로)."""
    return [
        {"robot_id": ns, "base_url": f"http://127.0.0.1:{api_port_base + i}",
         "token": SIM_OPERATOR_TOKEN}
        for i, ns in enumerate(namespaces)
    ]


def load_run_spec(path_text: str) -> dict:
    """D-426 T1: runner 소유 spec, 또는 {} (레거시 자체 생성 동작).

    검증 runner(tools/validation/fleet_gazebo/run.py)가 run별로 만든 파일만
    받는다. 필수 필드가 비면 즉시 실패한다(READY 거절 규칙 — 모호한 채로 뜨지 않는다).
    """
    path = (path_text or "").strip()
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    required = ("run_id", "core_config_dir", "fleet_manifest", "hub_url", "gz_partition")
    missing = [key for key in required if not spec.get(key)]
    if missing:
        raise RuntimeError(f"run_spec is missing runner fields: {', '.join(missing)}")
    return spec


def run_spec_overlay(spec: dict, ns: str) -> str:
    """runner 가 이미 쓴 CORE 오버레이 경로. 없으면 run_spec 이 잘못됐다."""
    path = os.path.join(spec["core_config_dir"], f"core_{ns}.yaml")
    if not os.path.isfile(path):
        raise RuntimeError(
            f"run_spec has no CORE overlay for {ns}: {path} is missing")
    return path


BRIDGE_TEMPLATE = [
    # (ros_topic, gz_topic, ros_type, gz_type, direction)
    ("scan", "scan", "sensor_msgs/msg/LaserScan", "gz.msgs.LaserScan", "GZ_TO_ROS"),
    ("cmd_vel", "cmd_vel", "geometry_msgs/msg/Twist", "gz.msgs.Twist", "ROS_TO_GZ"),
    ("joint_states", "joint_states", "sensor_msgs/msg/JointState", "gz.msgs.Model", "GZ_TO_ROS"),
    ("odom", "odom", "nav_msgs/msg/Odometry", "gz.msgs.Odometry", "GZ_TO_ROS"),
    ("odom_wheel", "odom_wheel", "nav_msgs/msg/Odometry", "gz.msgs.Odometry", "GZ_TO_ROS"),
    ("imu_raw", "imu_raw", "sensor_msgs/msg/Imu", "gz.msgs.IMU", "GZ_TO_ROS"),
]

CLOCK_ENTRY = {
    "ros_topic_name": "clock",
    "gz_topic_name": "clock",
    "ros_type_name": "rosgraph_msgs/msg/Clock",
    "gz_type_name": "gz.msgs.Clock",
    "direction": "GZ_TO_ROS",
}

#: TF 는 로봇마다 나누지 않는다. DiffDrive 플러그인이 `<tf_topic>/tf</tf_topic>` 로 gz 의
#: 전역 `/tf` 에 쓰고, robot_state_publisher 도 (네임스페이스와 무관하게) ROS 의 전역
#: `/tf` 에 쓴다. 프레임 이름은 frame_prefix 로 이미 `rosy_XX/` 가 붙어 충돌하지 않는다.
#: 로봇별로 `rosy_XX/tf` 를 브리지하면 구독자만 생기고 발행자가 없어 odom→base_footprint
#: 가 ROS 로 넘어오지 않는다(맵이 안 생기던 원인).
TF_ENTRY = {
    "ros_topic_name": "/tf",
    "gz_topic_name": "/tf",
    "ros_type_name": "tf2_msgs/msg/TFMessage",
    "gz_type_name": "gz.msgs.Pose_V",
    "direction": "GZ_TO_ROS",
}


def bridge_config(namespace: str, with_clock: bool = False) -> list:
    entries = []
    if with_clock:
        entries.append(dict(CLOCK_ENTRY))
        entries.append(dict(TF_ENTRY))
    for ros_topic, gz_topic, ros_type, gz_type, direction in BRIDGE_TEMPLATE:
        entries.append({
            "ros_topic_name": f"{namespace}{ros_topic}",
            "gz_topic_name": f"{namespace}{gz_topic}",
            "ros_type_name": ros_type,
            "gz_type_name": gz_type,
            "direction": direction,
        })
    return entries
