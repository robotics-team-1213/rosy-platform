#!/bin/bash
# b4_go.sh <name> <probe script> <probe args>: one probe run against the B4 sim (domain 80, port 8100).
WS=$HOME/rosy_b4_ws; E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
cd "$WS"; export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export ROS_DOMAIN_ID=80 GZ_PARTITION=rosy_b4 PYTHONPATH=$E:$PYTHONPATH
N=$1; S=$2; shift 2; O=b4runs/$N; rm -rf "$O"; mkdir -p "$O"
python3 "$S" "$@" --base http://127.0.0.1:8100 --out "$O" > "$O/probe.out" 2>&1
