#!/bin/bash
# One isolated Fleet lap; provide a unique OUTD and the fixed one_lap.txt.
WS=${WS:-$HOME/rosy_lane_loop_ws}; H=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
OUTD=${OUTD:-runs}
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/pyextra:$PYTHONPATH ROS_DOMAIN_ID=95 GZ_PARTITION=rosy_lane_loop
mkdir -p $OUTD
PYTHONPATH=$WS/pyfleet:$PYTHONPATH python3 "$H/lap_fleet.py" --core http://127.0.0.1:8594 --port 8595 --db $OUTD/fleet.sqlite3 --sends $OUTD/sends.jsonl > $OUTD/fleet.out 2>&1 &
F=$!
sleep 6
while read -r name args; do
  name=${name%$'\r'}; args=${args%$'\r'}
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> $OUTD/batch.log
  if [ -e "$OUTD/$name" ]; then echo "run exists: $OUTD/$name" >&2; break; fi
  mkdir -p "$OUTD/$name"
  [ "$REC" = "1" ] && { python3 "$H/lap_record.py" --out "$OUTD/$name/rec" --duration 1300 > "$OUTD/$name/rec.out" 2>&1 & R=$!; }
  timeout 1200 python3 "$H/lap_trip.py" --base http://127.0.0.1:8594 --fleet http://127.0.0.1:8595 --out "$OUTD/$name" $args > "$OUTD/$name/probe.out" 2>&1
  [ "$REC" = "1" ] && { kill -INT $R; wait $R; }
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('reason'), d.get('error'))" \
    "$OUTD/$name/summary.json" >> $OUTD/batch.log 2>&1
done < "$1"
kill $F
echo BATCH_DONE >> $OUTD/batch.log
