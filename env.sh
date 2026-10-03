#!/usr/bin/env bash
# env.sh — ROSY 개발 환경 공통 진입점
# 사용: source env.sh
#   - /opt/ros/$ROS_DISTRO/setup.bash source (기본 jazzy)
#   - 워크스페이스 install/setup.bash가 있으면 추가 source (colcon build 후)
# 빌드(저장소 root에서, D-427 colcon_roots):
#   source env.sh && colcon build --base-paths $(python3 tools/harness/colcon_roots.py) \
#       --build-base build --install-base install --log-base log

ROS_DISTRO="${ROS_DISTRO:-jazzy}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
    # shellcheck disable=SC1091
    source "/opt/ros/$ROS_DISTRO/setup.bash"
    echo "rosy env: ROS 2 $ROS_DISTRO sourced"
else
    echo "rosy env: WARNING - /opt/ros/$ROS_DISTRO not found" >&2
fi

if [ -f "$REPO_DIR/install/setup.bash" ]; then
    # shellcheck disable=SC1091
    source "$REPO_DIR/install/setup.bash"
    echo "rosy env: workspace install sourced"
fi

# D-117 / D-120: 개발·시뮬도 Cyclone. FastDDS 기본값과 deprecated ROS_LOCALHOST_ONLY 를 물려받지 않는다.
# 로봇에서는 이 파일을 source 하지 말고 rosy_env.sh 를 쓴다.
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"
echo "rosy env: RMW=$RMW_IMPLEMENTATION discovery=$ROS_AUTOMATIC_DISCOVERY_RANGE"

# 로봇(실기기)에서는 대신 bringup의 로봇별 격리 스크립트 사용:
#   source $(ros2 pkg prefix bringup)/share/bringup/scripts/rosy_env.sh 1
