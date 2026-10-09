#!/bin/bash
# D-573 (c) gate-on lap (model PC only): rosy-2a's one-lap run (lane-model-closed-loop
# closed_loop_batch.sh, threshold paint = the shipped keep path of xgate_sim.sh) on domain 63,
# CORE 8663, Fleet 8664: lap_trip.py from the D-513 start (-1.26955, 0.24255, -90 deg) to NW.
WS=${WS:-$HOME/rosy_xgate_ws}; H=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
OUTD=${OUTD:-runs_lap}   # ARGS: extra lap_trip.py args (start pose, --to)
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/pyextra:$PYTHONPATH ROS_DOMAIN_ID=63 GZ_PARTITION=rosy_xgate
mkdir -p $OUTD
PYTHONPATH=$WS/pyfleet:$PYTHONPATH python3 "$H/lap_fleet.py" --core http://127.0.0.1:8663 --port 8664 --db $OUTD/fleet.sqlite3 --sends $OUTD/sends.jsonl > $OUTD/fleet.out 2>&1 &
F=$!
sleep 6
for name in "$@"; do
  mkdir -p "$OUTD/$name"
  echo "=== $name $(date +%T)" >> $OUTD/batch.log
  timeout 1200 python3 "$H/lap_trip.py" --base http://127.0.0.1:8663 --fleet http://127.0.0.1:8664 --out "$OUTD/$name" $ARGS > "$OUTD/$name/probe.out" 2>&1
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('reason'), d.get('error'))" "$OUTD/$name/summary.json" >> $OUTD/batch.log 2>&1
done
kill $F
echo BATCH_DONE >> $OUTD/batch.log
