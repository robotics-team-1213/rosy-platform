#!/usr/bin/env bash
set -e
SRC="/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/pilot-teleop"
rm -rf /rosy/src/runtime/api_web
tar -C "$SRC" -cf - src/runtime/api_web | tar -C /rosy -xf -
# D-427: the source roots come from tools/harness/platform_parts.yaml.
COLCON_ROOTS="$(python3 "$(dirname "$0")/harness/colcon_roots.py")"
cd /rosy
source /opt/ros/jazzy/setup.bash
colcon --log-base log build --symlink-install --base-paths $COLCON_ROOTS --build-base build --install-base install \
    --packages-select core_api_web 2>&1 | tail -2
echo "=== restart sim ==="
pkill -f "gz_multi.launch.py" 2>/dev/null || true
pkill -f "ros_gz_bridge" 2>/dev/null || true
pkill -f "sim_jpeg_relay" 2>/dev/null || true
pkill -9 -f "lib/core/core" 2>/dev/null || true
pkill -f "gz sim" 2>/dev/null || true
sleep 3
echo "SYNC_RESTART_DONE"
