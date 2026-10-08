#!/bin/bash
# Lap SIM 2 (model PC only): the lap harness's run_sim.sh with its own workspace ~/rosy_lap2_ws,
# ROS domain 91, GZ_PARTITION rosy_lap2, CORE port 8388, run dir lap2, world lap2_fleet_real.world.
# Shipped line_follow defaults + obstacle_mode path, ir_guard_enabled, site_floor_map_id map_v2_fleet.
#   [ARC=1] setsid nohup bash lap2_run.sh > ~/rosy_lap2_ws/sim.out 2>&1 < /dev/null &
# ARC=1: also D-520 line_follow.arc_enabled: true (its documented switch; shipped default false).
WS=$HOME/rosy_lap2_ws
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/lap2#' -e 's#d495_fleet_real.world#lap2_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_lap2.sh"
[ "${ARC:-0}" = "1" ] && sed -i '/^  ir_guard_enabled: true$/a\  arc_enabled: true' "$E/run_sim_lap2.sh"
WS=$WS PORT=8388 ROS_DOMAIN_ID=91 GZ_PARTITION=rosy_lap2 exec bash "$E/run_sim_lap2.sh" "$@"
