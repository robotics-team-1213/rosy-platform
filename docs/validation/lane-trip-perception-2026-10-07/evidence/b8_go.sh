#!/bin/bash
# b8_go.sh <name> <d495_sim_probe.py args>: record (b8_record.py) while the D-495 probe drives.
# Output: ~/rosy_d495_ws/b8runs/<name>/ (probe log/summary + frames.npz + keep.jsonl).
cd ~/rosy_d495_ws
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export ROS_DOMAIN_ID=78 GZ_PARTITION=rosy_b8
N=$1; shift; O=b8runs/$N; rm -rf "$O"; mkdir -p "$O"
python3 b8/b8_record.py --out "$O/rec" --duration 600 > "$O/rec.out" 2>&1 &
R=$!
python3 evidence/d495_sim_probe.py "$@" --base http://127.0.0.1:8098 --out "$O" > "$O/probe.out" 2>&1
kill -INT $R; wait $R
tail -1 "$O/rec.out"
