#!/bin/bash
# D-573 (c) gate-on crosswalk SIM (model PC only). The baseline's xwalk_sim.sh with its own isolation
# (workspace ~/rosy_xgate_ws, ROS domain 63, GZ_PARTITION rosy_xgate, CORE 8663, run dir xgate) and
# line_follow.crosswalk_gate_enabled: true added to the CORE overlay. MemoryMax 6G.
WS=${WS:-$HOME/rosy_xgate_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
GATE=${GATE:-true}
# SIGMA (m): the SIM LiDAR range noise for this scenario only; set to the measured C1 value
# (8kcn 2026-10-10: max 3.4 mm over 0-0.5 m) with a 1 mm range resolution. Edits this workspace's
# copy of rosy_gz.urdf.xacro (symlink install), never the repo; unset keeps the shipped 0.02/0.03.
D=$WS/src/rosy-platform/middleware/apps/device/pinky/description/urdf/rosy_gz.urdf.xacro
if [ -n "$SIGMA" ]; then
  sed -i -e "s#<stddev>[0-9.]*</stddev>#<stddev>$SIGMA</stddev>#"     -e "/<range>/,/<\/range>/s#<resolution>[0-9.]*</resolution>#<resolution>0.001</resolution>#" "$D"
fi
# The runners log CORE line_follow.crosswalk too (D-573 6), this workspace's copy only.
L=$WS/src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence/lap_trip.py
grep -q "'stuck', 'crosswalk')" "$L" || sed -i "s#'confidence', 'stuck')#'confidence', 'stuck', 'crosswalk')#" "$L"
sed -e 's#RUN=$WS/d495#RUN=$WS/xgate#' -e 's#d495_fleet_real.world#xgate_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet\n  crosswalk_gate_enabled: '"$GATE"'#' \
  -e 's#^ros2 launch #systemd-run --user --scope -q -p MemoryMax=6G ros2 launch #' \
  "$E/run_sim.sh" > "$E/run_sim_xgate.sh"
WS=$WS PORT=8663 ROS_DOMAIN_ID=63 GZ_PARTITION=rosy_xgate exec bash "$E/run_sim_xgate.sh" "$@"
