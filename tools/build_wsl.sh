#!/usr/bin/env bash
# Pilot T7 시뮬레이션 루프를 위한 웍트리 colcon 빌드(WSL Jazzy).
set -e
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
colcon build --symlink-install 2>&1 | tail -n 25
echo "BUILD_DONE"
