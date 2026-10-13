#!/bin/bash
# sim-model-lap 2026-10-09 (model PC only): one isolated closed-loop lap per call.
# lane-model-closed-loop-2026-10-09 run_closed_loop.sh + closed_loop_batch.sh, with
#   own ws/domain/partition/ports, line_follow.arc_enabled false (device realism),
#   learned_paint_every_n / motion_compensation, ROSY_SIM_PAINT_LATENCY_MS (paint worker sleep).
#   bash m26_one.sh NAME MODEL_DIR|threshold EVERY_N COMP(true|false) LAT_MS
NAME=$1 MODEL=$2 EVERY_N=${3:-2} COMP=${4:-false} LAT_MS=${5:-0} ARC=${ARC:-false}
export WS=${WS:-$HOME/rosy_m26_ws}
PORT=8604 FPORT=8605
export ROS_DOMAIN_ID=97 GZ_PARTITION=rosy_m26
H=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
OUT=$WS/runs/$NAME
[ -e "$OUT" ] && { echo "exists $OUT" >&2; exit 2; }
mkdir -p "$OUT"
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/pyextra:$PYTHONPATH
export ROSY_LEARNED_SITE=$HOME/rosy-ml/.venv/lib/python3.12/site-packages
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH
done
export ROSY_SIM_PAINT_LATENCY_MS=$LAT_MS
stop_all() {
  for p in $(pgrep -u "$(id -u)"); do
    [ "$p" = "$$" ] && continue
    tr '\000' '\n' 2>/dev/null < /proc/$p/environ | grep -qx "GZ_PARTITION=$GZ_PARTITION" && kill "$p" 2>/dev/null
  done
  sleep 4
}
stop_all
SHARE=$(ros2 pkg prefix gz_sim)/share/gz_sim
sed "s/api_port: 8080/api_port: $PORT/" "$SHARE/config/map_v2_fleet_core.yaml" > "$OUT/core_overlay.yaml"
cat >> "$OUT/core_overlay.yaml" <<YAML
line_follow:
  obstacle_mode: path
  ir_guard_enabled: true
  site_floor_map_id: map_v2_fleet
  arc_enabled: $ARC
YAML
cp "$(ros2 pkg prefix control)/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world" "$OUT/m26_fleet_real.world"
if [ "$MODEL" = threshold ]; then ARGS=(paint_source:=threshold)
else echo "$MODEL" > "$OUT/pointer"; ARGS=(paint_source:=learned "learned_lane_pointer:=$OUT/pointer"); fi
echo "{\"name\":\"$NAME\",\"model\":\"$MODEL\",\"every_n\":$EVERY_N,\"comp\":$COMP,\"latency_ms\":$LAT_MS,\"arc_enabled\":$ARC,\"start\":\"$(date -Is)\"}" > "$OUT/config.json"
systemd-run --user --scope -q -p MemoryMax=6G -p CPUQuota=800% \
  ros2 launch "$WS/m26_loop.launch.py" core_overlay:="$OUT/core_overlay.yaml" world:="$OUT/m26_fleet_real.world" \
  camera_lane_mode:=keep learned_paint_every_n:=$EVERY_N learned_paint_motion_compensation:=$COMP "${ARGS[@]}" \
  > "$OUT/launch.log" 2>&1 &
for i in $(seq 90); do [ "$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/")" != 000 ] && break; sleep 2; done
sleep 20
PYTHONPATH=$WS/pyfleet:$PYTHONPATH python3 "$H/lap_fleet.py" --core http://127.0.0.1:$PORT --port $FPORT --db $OUT/fleet.sqlite3 --sends $OUT/sends.jsonl > $OUT/fleet.out 2>&1 &
F=$!
sleep 6
python3 "$H/lap_record.py" --out "$OUT/rec" --duration 1300 > "$OUT/rec.out" 2>&1 & R=$!
timeout 1200 python3 "$H/lap_trip.py" --base http://127.0.0.1:$PORT --fleet http://127.0.0.1:$FPORT --out "$OUT/lap" > "$OUT/probe.out" 2>&1
kill -INT $R; wait $R
kill $F
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('reason'), d.get('error'))" "$OUT/lap/summary.json" > "$OUT/result.txt" 2>&1
stop_all
echo DONE >> "$OUT/result.txt"
