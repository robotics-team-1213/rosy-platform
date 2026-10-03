#!/usr/bin/env bash
# Pilot T7 시뮬레이션 루프를 위한 웍트리 colcon 빌드(WSL Jazzy).
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# D-427: the source roots come from tools/harness/platform_parts.yaml.
COLCON_ROOTS="$(python3 tools/harness/colcon_roots.py)"
colcon build --symlink-install --base-paths $COLCON_ROOTS \
    --build-base build --install-base install --log-base log 2>&1 | tail -n 25
echo "BUILD_DONE"
