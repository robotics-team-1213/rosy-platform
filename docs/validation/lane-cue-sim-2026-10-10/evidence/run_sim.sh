#!/bin/bash
# D-511 CORE Fleet lane cue SIM (model PC only; never on the Windows laptop). One Pinky on
# map_v2_fleet_real in CAMERA_LINE keep through the D-495 launch (d495_real.launch.py: Gazebo,
# ground truth on d495/gt, paint-aware IR, line_observer, CORE on sim time).
#
#   WS=~/rosy_lcsim_ws nohup bash run_sim.sh > sim.out 2>&1 &
#
# CORE overlay = gz_sim config/map_v2_fleet_core.yaml (api_port $PORT) + the lane cue flag with
# obstacle_mode path (model.py refuses the flag without it) + one Fleet-seat token: an operator
# token from source pair-physical labelled "site:lane-cue-sim", the D-555 3 seat lane_cue_seat()
# takes, and a plain operator token for the probe. Plaintexts are made per run in $RUN (never in the repo).
WS=${WS:-$HOME/rosy_lcsim_ws}
PORT=${PORT:-8671}
D495=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$PYTHONPATH
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH   # namespace package rosy.* (contracts/motion etc.)
done
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-67} GZ_PARTITION=${GZ_PARTITION:-rosy_lcsim}
RUN=$WS/lcsim; mkdir -p "$RUN"
SHARE=$(ros2 pkg prefix gz_sim)/share/gz_sim
python3 - "$RUN" <<'PY'
import secrets, sys, yaml
from core_api_web.api.deps import new_token_record, stored_token_entries
# An overlay token list replaces the dev tokens (ROSY_DEV_AUTH), so the probe's operator token is
# made here too: op_token (mode, status) and site_token (the lane cue seat).
site, op = ("lcsim-" + secrets.token_hex(16) for _ in range(2))
open(sys.argv[1] + "/site_token", "w").write(site)
open(sys.argv[1] + "/op_token", "w").write(op)
entry = stored_token_entries([new_token_record(site, "operator", "site:lane-cue-sim", source="pair-physical"),
                              new_token_record(op, "operator", "lane-cue-sim probe")])
yaml.safe_dump({"auth": {"tokens": entry}}, open(sys.argv[1] + "/token_layer.yaml", "w"))
PY
sed "s/api_port: 8080/api_port: $PORT/" "$SHARE/config/map_v2_fleet_core.yaml" > "$RUN/core_overlay.yaml"
cat >> "$RUN/core_overlay.yaml" <<YAML
line_follow:
  obstacle_mode: path
  ir_guard_enabled: true
  fleet_lane_cue_enabled: true
YAML
cat "$RUN/token_layer.yaml" >> "$RUN/core_overlay.yaml"
# Stop every process of an earlier run of this partition (stale bridges double odom; D-495 note).
for p in $(pgrep -u "$(id -u)"); do
  [ "$p" = "$$" ] && continue
  tr '\000' '\n' 2>/dev/null < /proc/$p/environ | grep -qx "GZ_PARTITION=$GZ_PARTITION" && kill "$p" 2>/dev/null
done
sleep 4
cp "$(ros2 pkg prefix control)/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world" "$RUN/lcsim_fleet_real.world"
systemd-run --user --scope -q -p MemoryMax=6G ros2 launch "$D495/d495_real.launch.py" \
  core_overlay:="$RUN/core_overlay.yaml" world:="$RUN/lcsim_fleet_real.world" "$@" > "$RUN/launch.log" 2>&1 &
LPID=$!
echo "sim up: CORE http://127.0.0.1:$PORT domain $ROS_DOMAIN_ID partition $GZ_PARTITION (launch pid $LPID)"
wait $LPID
