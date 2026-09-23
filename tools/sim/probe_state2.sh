#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# 살아있는 ROS 프로세스에서 도메인·RMW를 자동 일치시켜 그래프를 본다
source /opt/ros/jazzy/setup.bash 2>/dev/null
source "$REPO/install/setup.bash" 2>/dev/null

DOMAIN=""
for pid in $(pgrep -f 'robot.launch.py|gz_multi|core' | head -10); do
  d=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep '^ROS_DOMAIN_ID=' | cut -d= -f2)
  [ -n "$d" ] && { DOMAIN="$d"; break; }
done
echo "발견된 도메인: '${DOMAIN}'"
export ROS_DOMAIN_ID="${DOMAIN:-0}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

echo "--- 토픽 전체(핵심만) ---"
timeout 12 ros2 topic list 2>/dev/null | grep -E 'scan|map|odom|tf$|cmd_vel' | head -12
echo "--- /rosy_01/scan Hz ---"
timeout 6 ros2 topic hz /rosy_01/scan 2>&1 | head -2
echo "--- /rosy_01/map 或 /map ---"
timeout 6 ros2 topic list 2>/dev/null | grep -iE '/map' | head -4
echo "--- tf map->rosy_01/base_footprint ---"
timeout 8 ros2 run tf2_ros tf2_echo map rosy_01/base_footprint 2>&1 | head -3
