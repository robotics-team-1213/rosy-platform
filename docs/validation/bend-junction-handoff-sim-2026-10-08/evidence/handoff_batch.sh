#!/bin/bash
# lap batch.sh with workspace ~/rosy_handoff_ws, domain 89, partition rosy_handoff, ports 8288/8289.
WS=$HOME/rosy_handoff_ws; H=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
OUTD=${OUTD:-runs}
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/pyextra:$PYTHONPATH ROS_DOMAIN_ID=89 GZ_PARTITION=rosy_handoff
mkdir -p $OUTD
PYTHONPATH=$WS/pyfleet:$PYTHONPATH python3 "$H/lap_fleet.py" --core http://127.0.0.1:8288 --port 8289 --db $OUTD/fleet.sqlite3 --sends $OUTD/sends.jsonl > $OUTD/fleet.out 2>&1 &
F=$!
sleep 6
while read -r name args; do
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> $OUTD/batch.log
  rm -rf "$OUTD/$name"; mkdir -p "$OUTD/$name"
  [ "$REC" = "1" ] && { python3 "$H/lap_record.py" --out "$OUTD/$name/rec" --duration 1300 > "$OUTD/$name/rec.out" 2>&1 & R=$!; }
  eval timeout 1200 python3 "$H/lap_trip.py" --base http://127.0.0.1:8288 --fleet http://127.0.0.1:8289 --out "$OUTD/$name" $args > "$OUTD/$name/probe.out" 2>&1
  [ "$REC" = "1" ] && { kill -INT $R; wait $R; }
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('reason'), d.get('error'))" \
    "$OUTD/$name/summary.json" >> $OUTD/batch.log 2>&1
done < "${1:-$H/batch.txt}"
kill $F
echo BATCH_DONE >> $OUTD/batch.log
