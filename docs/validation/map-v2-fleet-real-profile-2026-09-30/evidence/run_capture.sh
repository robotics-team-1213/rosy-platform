#!/bin/bash
# usage: run_capture.sh OUTDIR TAG [launch file] [extra launch args...]
WS=${WS:-/rosy_realprof_ws}
OUT=$1; TAG=$2; LF=${3:-map_v2_fleet_real.launch.py}; shift 3
cd $WS
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=53
export GZ_PARTITION=rosy_realprof
mkdir -p "$OUT"
# kill only our own previous runs (partition tag in env is not visible in ps; match our world/ws)
pkill -f "ros2 launch gz_sim $LF"; pkill -f "gz sim -r -s -v4 /rosy_realprof_ws"; sleep 2
setsid ros2 launch gz_sim $LF "$@" > "$OUT/launch_$TAG.log" 2>&1 &
LPID=$!
for i in $(seq 1 60); do sleep 2; ros2 topic list 2>/dev/null | grep -q camera/front && break; done
sleep 10
timeout 300 python3 "$(dirname "$0")/../capture_frames.py" "$OUT" $WS/install/control/share/control/map/map_v2_fleet/lane_graph.yaml 20 "$TAG"
echo "--- nodes"; ros2 node list
echo "--- launch errors"; grep -iE "unable to find|could not|\[error\]|exception|traceback" "$OUT/launch_$TAG.log" | head -15
kill -INT -- -$LPID; sleep 6; kill -TERM -- -$LPID 2>/dev/null; sleep 2; kill -KILL -- -$LPID 2>/dev/null
pkill -f "ros2 launch gz_sim $LF"; pkill -f "gz sim -r -s -v4 $WS"; sleep 1
ps aux | grep -E "rosy_realprof" | grep -v grep | grep -v run_capture | head -5
echo DONE
