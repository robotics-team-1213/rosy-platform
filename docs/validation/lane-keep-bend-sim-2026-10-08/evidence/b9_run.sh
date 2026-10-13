#!/bin/bash
# B9 sim (model PC only): the D-495 run_sim.sh unchanged except its own workspace (~/rosy_b9_ws,
# built from fix/keep-bend-not-fork), ROS domain 79, GZ_PARTITION rosy_b9, CORE port 8099, run dir
# $WS/b9 and world file name, so the B8/D-495/D-476 sessions on this host are not touched.
#   RECOVERY=false [GATE=1] setsid nohup bash b9_run.sh > ~/rosy_b9_ws/b9_sim.out 2>&1 < /dev/null &
# GATE=1: sim_gate/sitecustomize.py turns the keeper's bend_expected on (B11/B12 stand-in).
# D-507 9 (main since 2026-10-08) removed bridge_site_no_dropoffs / junction_turn_site_accepted:
# the site basis is now the floor declaration site_floor_map_id (map_v2_fleet, the world's map id).
WS=${WS:-$HOME/rosy_b9_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/b9#' -e 's#d495_fleet_real.world#b9_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_b9.sh"
[ "${GATE:-0}" = "1" ] && export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/sim_gate:$PYTHONPATH"
WS=$WS PORT=8099 ROS_DOMAIN_ID=79 GZ_PARTITION=rosy_b9 exec bash "$E/run_sim_b9.sh" "$@"
