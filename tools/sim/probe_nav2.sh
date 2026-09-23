#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/jazzy/setup.bash 2>/dev/null
source "$REPO/install/setup.bash" 2>/dev/null
GZ_PID=$(pgrep -f 'gz_multi.launch.py' | head -1)
DOMAIN=$(tr '\0' '\n' < "/proc/$GZ_PID/environ" 2>/dev/null | grep '^ROS_DOMAIN_ID=' | cut -d= -f2)
echo "sim domain: '$DOMAIN'"
export ROS_DOMAIN_ID="${DOMAIN:-0}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
echo "--- topics (map/tf/scan) ---"
timeout 12 ros2 topic list 2>/dev/null | grep -E 'map|tf|scan' | head -12
echo "--- nodes (amcl/map_server) ---"
timeout 12 ros2 node list 2>/dev/null | grep -E 'amcl|map_server|slam' | head -6
echo "--- tf map->rosy_01/base_footprint ---"
timeout 8 ros2 run tf2_ros tf2_echo map rosy_01/base_footprint 2>&1 | head -4
