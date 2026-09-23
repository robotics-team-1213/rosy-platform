#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE=http://127.0.0.1:8090
echo "--- fleet state ---"
curl -s --max-time 6 $BASE/api/fleet/state | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('online:', d['fleet']['online'], '/', d['fleet']['total'])
for r in d['robots']:
    st = r.get('state') or {}
    print(' ', r['robot_id'], '| online', r['online'], '| nav', st.get('navigation'), '| pose', st.get('pose'))
"
echo "--- formation ---"
curl -s --max-time 6 $BASE/api/fleet/formation | python3 -c "
import json, sys
f = json.load(sys.stdin)
r = f.get('relay') or {}
print(f.get('state'), '| leader_hz', r.get('leader_rx_hz'), '| tx_hz', r.get('follower_tx_hz'), '| conn', r.get('follower_connected'), '| err', r.get('follower_last_error'))
"
echo "--- tokens ---"
curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 $BASE/ui/tokens.css
echo "--- map topic (시뮬 도메인) ---"
GZ_PID=$(pgrep -f 'gz_multi.launch.py' | head -1)
DOMAIN=$(tr '\0' '\n' < "/proc/$GZ_PID/environ" 2>/dev/null | grep '^ROS_DOMAIN_ID=' | cut -d= -f2)
echo "sim domain: $DOMAIN"
source /opt/ros/jazzy/setup.bash 2>/dev/null
source "$REPO/install/setup.bash" 2>/dev/null
export ROS_DOMAIN_ID="${DOMAIN:-0}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
timeout 8 ros2 topic list 2>/dev/null | grep -E '/map$|/scan|amcl_pose' | head -6
timeout 6 ros2 topic hz /rosy_01/scan 2>&1 | head -2
