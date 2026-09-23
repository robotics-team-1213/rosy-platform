#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE=http://127.0.0.1:8090
echo "--- state ---"
curl -s --max-time 6 $BASE/api/fleet/state | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('online:', d['fleet']['online'], '/', d['fleet']['total'])
for r in d['robots']:
    st = r.get('state') or {}
    print(' ', r['robot_id'], '| online', r['online'], '| nav', st.get('navigation'), '| pose', (st.get('pose') or {}).get('x'), (st.get('pose') or {}).get('y'), '| map', st.get('map_id'))
"
echo "--- formation ---"
curl -s --max-time 6 $BASE/api/fleet/formation | head -c 300
echo
echo "--- scan 토픽(센서 브리지 생존 확인) ---"
GZ_PID=$(pgrep -f 'gz_multi.launch.py' | head -1)
DOMAIN=$(tr '\0' '\n' < "/proc/$GZ_PID/environ" 2>/dev/null | grep '^ROS_DOMAIN_ID=' | cut -d= -f2)
echo "domain: '$DOMAIN'"
source /opt/ros/jazzy/setup.bash 2>/dev/null
source "$REPO/install/setup.bash" 2>/dev/null
export ROS_DOMAIN_ID="${DOMAIN:-0}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
timeout 6 ros2 topic list 2>/dev/null | grep -E '/rosy_01/scan|/rosy_01/map|/clock' | head -5
timeout 5 ros2 topic hz /rosy_01/scan 2>&1 | head -1
