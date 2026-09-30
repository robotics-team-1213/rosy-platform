#!/usr/bin/env bash
# Pilot 시뮬 (헤드리스) — GUI 없이 서버+센서만. 카메라는 EGL 오프스크린 렌더.
set -e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROSY_DEV_AUTH=1
# 이전 프로세스 정리
pkill -9 -f "gz_multi.launch.py" 2>/dev/null || true
pkill -9 -f "gz sim" 2>/dev/null || true
pkill -9 -f "parameter_bridge" 2>/dev/null || true
pkill -9 -f "ros_gz_bridge" 2>/dev/null || true
pkill -9 -f "sim_jpeg_relay" 2>/dev/null || true
pkill -9 -f "image_transport" 2>/dev/null || true
pkill -9 -f "lib/core/core" 2>/dev/null || true
sleep 2
MAP_YAML="$PWD/src/runtime/sensing/map/map_260905_update_v2/maps/map_260905.yaml"
exec ros2 launch gz_sim gz_multi.launch.py robots:=1 mode:=nav core:=true \
  headless:=true world_name:=rosy_factory.world map:="$MAP_YAML" spawn_x:=-0.5
