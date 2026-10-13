#!/bin/bash
# D-507 B13 lap SIM (model PC only): the D-495 run_sim.sh with its own workspace
# (~/rosy_lapsim_ws), ROS domain 88, GZ_PARTITION rosy_lapsim, CORE port 8188, run dir and
# world file name, so other sessions on this host are not touched. Site overlay: the shipped
# line_follow defaults (recovery_local_enabled true, bridge_enabled false) plus obstacle_mode
# path, ir_guard_enabled true and site_floor_map_id map_v2_fleet; keep mode is the launch default.
#   setsid nohup bash lap_run.sh > ~/rosy_lapsim_ws/sim.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_lapsim_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/lapsim#' -e 's#d495_fleet_real.world#lapsim_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_lapsim.sh"
WS=$WS PORT=8188 ROS_DOMAIN_ID=88 GZ_PARTITION=rosy_lapsim exec bash "$E/run_sim_lapsim.sh" "$@"
