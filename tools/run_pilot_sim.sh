#!/usr/bin/env bash
# Pilot T7 시뮬레이션 루프(WSL, 웍트리 루트에서 실행).
# 가제보 GUI + 로봇 1대 + CORE(127.0.0.1:8080, /pilot 포함).
# 태블릿: adb reverse tcp:8080 tcp:8080 → http://localhost:8080/pilot/
# 토큰: rosy-dev-operator (ROSY_DEV_AUTH=1 시뮬 전용 개발 토큰)
set -e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROSY_DEV_AUTH=1
killall -9 ruby gz python3 parameter_bridge create 2>/dev/null || true
MAP_YAML="$PWD/middleware/perception/map/map_260905_update_v2/maps/map_260905.yaml"
exec ros2 launch gz_sim gz_multi.launch.py robots:=1 mode:=nav core:=true \
  headless:=false world_name:=rosy_factory.world map:="$MAP_YAML" spawn_x:=-0.5
