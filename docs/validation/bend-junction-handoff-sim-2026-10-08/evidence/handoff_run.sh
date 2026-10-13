#!/bin/bash
# bend->junction handoff SIM (model PC only): lap_run.sh with its own workspace, domain 89,
# GZ_PARTITION rosy_handoff, CORE port 8288, run dir handoff, world file handoff_fleet_real.world.
WS=$HOME/rosy_handoff_ws
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/handoff#' -e 's#d495_fleet_real.world#handoff_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_handoff.sh"
# ARC=1: also D-520 arc_enabled (shipped default off)
[ "${ARC:-0}" = "1" ] && sed -i '/^  ir_guard_enabled: true$/a\  arc_enabled: true' "$E/run_sim_handoff.sh"
WS=$WS PORT=8288 ROS_DOMAIN_ID=89 GZ_PARTITION=rosy_handoff exec bash "$E/run_sim_handoff.sh" "$@"
