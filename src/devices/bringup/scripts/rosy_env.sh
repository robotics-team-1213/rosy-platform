#!/usr/bin/env bash
# rosy_env.sh — 로봇별 DDS 격리 환경 설정 (P0-5, A-6 / ROSY-PLN-001)
#
# 사용: source rosy_env.sh <로봇번호>
#   예) source rosy_env.sh 1   → ROSY 01: ROS_DOMAIN_ID=41, localhost-only DDS
#
# 정책 (ADR-D-6):
#   - 로봇별 고유 ROS_DOMAIN_ID (base 40 + N, 유효 범위 0~101 내)
#   - CycloneDDS localhost 전용 프로파일로 타 로봇/타 기기 DDS 발견 차단
#   - 시뮬레이션 호스트에서 여러 로봇을 띄울 때는 이 스크립트를 쓰지 않고
#     gz_multi.launch.py + 동일 도메인 사용 (로봇별 namespace로 분리)

set -euo pipefail

ROBOT_NUM="${1:-}"
if [[ -z "$ROBOT_NUM" ]]; then
    echo "usage: source rosy_env.sh <robot-number>   (예: source rosy_env.sh 1)" >&2
    return 1 2>/dev/null || exit 1
fi

DOMAIN_BASE=40
export ROS_DOMAIN_ID=$((DOMAIN_BASE + ROBOT_NUM))
# 도메인만 나눠서는 부족하다 — 네임스페이스가 같으면 토픽 이름이 그대로 겹친다.
# 두 값 모두 같은 로봇 번호 하나에서 나온다 (ADR D-33).
export ROSY_NAMESPACE="$(printf 'rosy_%02d' "$ROBOT_NUM")"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

PROFILE="$(ros2 pkg prefix bringup)/share/bringup/config/cyclonedds_localhost.xml"
if [[ -f "$PROFILE" ]]; then
    export CYCLONEDDS_URI="file://$PROFILE"
else
    echo "warning: cyclonedds_localhost.xml not found ($PROFILE) — 프로파일 미적용" >&2
fi

echo "ROSY env: ROS_DOMAIN_ID=$ROS_DOMAIN_ID ROSY_NAMESPACE=$ROSY_NAMESPACE RMW=$RMW_IMPLEMENTATION"
