#!/bin/bash
# D-507 B13 lap SIM batch (model PC only): the Fleet server (lap_fleet.py) and one lap_trip.py
# run per line of the list (<name> <lap_trip args>), into ~/rosy_lapsim_ws/runs/<name>/.
#   [REC=1] setsid nohup bash batch.sh [list] > ~/rosy_lapsim_ws/batch.out 2>&1 < /dev/null &
WS=$HOME/rosy_lapsim_ws; H=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/pyextra:$PYTHONPATH ROS_DOMAIN_ID=88 GZ_PARTITION=rosy_lapsim
mkdir -p runs
# pyfleet: cryptography>=43 for fleet.server (uv pip install --python /usr/bin/python3 --target pyfleet)
PYTHONPATH=$WS/pyfleet:$PYTHONPATH python3 "$H/lap_fleet.py" --db runs/fleet.sqlite3 --sends runs/sends.jsonl > runs/fleet.out 2>&1 &
F=$!
sleep 6
while read -r name args; do
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> runs/batch.log
  rm -rf "runs/$name"; mkdir -p "runs/$name"
  # REC=1: also the camera frames, keep_debug bundles, odom and ground truth (lap_record.py)
  [ "$REC" = "1" ] && { python3 "$H/lap_record.py" --out "runs/$name/rec" --duration 1300 > "runs/$name/rec.out" 2>&1 & R=$!; }
  eval timeout 1200 python3 "$H/lap_trip.py" --out "runs/$name" $args > "runs/$name/probe.out" 2>&1
  [ "$REC" = "1" ] && { kill -INT $R; wait $R; }
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('reason'), d.get('error'))" \
    "runs/$name/summary.json" >> runs/batch.log 2>&1
done < "${1:-$H/batch.txt}"
kill $F
echo BATCH_DONE >> runs/batch.log
