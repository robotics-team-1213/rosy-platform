#!/bin/bash
# b9_go.sh <name> <d495_sim_probe.py args>: record (B8 b8_record.py) while the D-495 probe drives.
# Output: ~/rosy_b9_ws/b9runs/<name>/ (probe log/summary + rec/frames.npz + rec/keep.jsonl).
WS=$HOME/rosy_b9_ws; R8=$WS/src/rosy-platform/docs/validation
cd "$WS"
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export ROS_DOMAIN_ID=79 GZ_PARTITION=rosy_b9
N=$1; shift; O=b9runs/$N; rm -rf "$O"; mkdir -p "$O"
python3 "$R8/lane-trip-perception-2026-10-07/evidence/b8_record.py" --out "$O/rec" --duration 600 > "$O/rec.out" 2>&1 &
R=$!
python3 "$R8/d495-junction-sim-2026-10-07/evidence/d495_sim_probe.py" "$@" --base http://127.0.0.1:8099 --out "$O" > "$O/probe.out" 2>&1
kill -INT $R; wait $R
tail -1 "$O/rec.out"
