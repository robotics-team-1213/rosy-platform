#!/usr/bin/env bash
# 릴레이 전용 런처 — ROS env 를 반드시 태운다. 중복 실행은 막는다.
source /opt/ros/jazzy/setup.bash
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
if pgrep -f "sim_jpeg_relay.py" > /dev/null; then
  echo "relay already running"
  exit 0
fi
nohup python3 /rosy/tools/sim_jpeg_relay.py --ros-args -r __ns:=/rosy_01 \
  > /tmp/rosy_relay.log 2>&1 &
echo "relay pid $!"
sleep 3
pgrep -f "sim_jpeg_relay.py" > /dev/null && echo "relay alive" || { echo "relay DIED"; tail -5 /tmp/rosy_relay.log; }
