#!/bin/bash
set -eo pipefail
WS=/home/rosy/rosy_lfstop_ws
RUN=$WS/route_a_sim/offroute50_trip
mkdir -p "$RUN"
source /opt/ros/jazzy/setup.bash
source "$WS/install/setup.bash"
set -u
export ROS_DOMAIN_ID=101 GZ_PARTITION=rosy_lane_route101
python3 "$WS/src/rosy-platform/docs/validation/lane-trip-perception-2026-10-07/evidence/b8_record.py" --out "$RUN/rec" --duration 50 > "$RUN/rec.out" 2>&1 &
rec_pid=$!
trap 'kill -INT "$rec_pid" 2>/dev/null || true; wait "$rec_pid" 2>/dev/null || true' EXIT
sleep 3
python3 "$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence/d495_sim_probe.py" trip --x -1.15 --y -0.461 --yaw 0 --plan left:60 --duration 20 --base http://127.0.0.1:8111 --out "$RUN" > "$RUN/probe.out" 2>&1
