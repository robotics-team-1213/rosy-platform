#!/bin/bash
# Lap SIM 4 (model PC only): lap SIM 3's ring_run.sh with its own workspace ~/rosy_ring4_ws, ROS domain 93,
# GZ_PARTITION rosy_ring4, CORE port 8588, run dir ring4, world ring4_fleet_real.world.
# Shipped line_follow defaults (arc_enabled now true by default) + obstacle_mode path, ir_guard_enabled,
# site_floor_map_id map_v2_fleet. No arc switch: the ring arc runs because the site floor is declared.
#   setsid nohup bash ring4_run.sh > ~/rosy_ring4_ws/sim.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_ring4_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/ring4#' -e 's#d495_fleet_real.world#ring4_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_ring4.sh"
WS=$WS PORT=8588 ROS_DOMAIN_ID=93 GZ_PARTITION=rosy_ring4 exec bash "$E/run_sim_ring4.sh" "$@"
