#!/bin/bash
# D-573 (g) crosswalk baseline batch (model PC only): lap_fleet.py on port 8662 against CORE 8661,
# then one xwalk_run.py per line of the list: <name> <ped>. Domain 61, partition rosy_xwalk.
#   OUTD=runs setsid nohup bash xwalk_batch.sh xwalk_batch.txt > ~/rosy_xwalk_ws/batch.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_xwalk_ws}
H=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
X=$(cd "$(dirname "$0")" && pwd)
OUTD=${OUTD:-runs}
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/pyextra:$PYTHONPATH ROS_DOMAIN_ID=61 GZ_PARTITION=rosy_xwalk
mkdir -p $OUTD
PYTHONPATH=$WS/pyfleet:$PYTHONPATH python3 "$H/lap_fleet.py" --core http://127.0.0.1:8661 --port 8662 --db $OUTD/fleet.sqlite3 --sends $OUTD/sends.jsonl > $OUTD/fleet.out 2>&1 &
F=$!
sleep 6
while read -r name ped; do
  name=${name%$'\r'}; ped=${ped%$'\r'}
  [ -z "$name" ] && continue
  echo "=== $name $ped $(date +%T)" >> $OUTD/batch.log
  rm -rf "$OUTD/$name"; mkdir -p "$OUTD/$name"
  timeout 300 python3 "$X/xwalk_run.py" --out "$OUTD/$name" --ped "$ped" > "$OUTD/$name/probe.out" 2>&1
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('verdict'), d.get('min_gap_to_ped_m'), (d.get('first_stop') or {}).get('reason'), (d.get('trip_at_end') or {}).get('state'), d.get('error'))" \
    "$OUTD/$name/summary.json" >> $OUTD/batch.log 2>&1
done < "$1"
kill $F
echo BATCH_DONE >> $OUTD/batch.log
