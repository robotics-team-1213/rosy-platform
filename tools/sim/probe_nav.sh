#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/jazzy/setup.bash 2>/dev/null
source "$REPO/install/setup.bash" 2>/dev/null
echo "--- map/slam/amcl procs ---"
ps aux | grep -E '[m]ap_server|[s]lam|[a]mcl' | awk '{print $11, $12, $13}' | head -5
echo "--- ros2 topic list (map/tf 관련) ---"
timeout 10 ros2 topic list 2>/dev/null | grep -E 'map|tf|scan' | head -10
echo "--- rosy_01 amcl 피드백 확인 ---"
timeout 10 ros2 topic echo /rosy_01/amcl_pose --once 2>/dev/null | head -6 || echo "amcl_pose 없음"
