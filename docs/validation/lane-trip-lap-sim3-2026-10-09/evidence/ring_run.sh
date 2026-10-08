#!/bin/bash
# Lap SIM 3 (model PC only): lap2_run.sh with its own workspace ~/rosy_ring_ws, ROS domain 92,
# GZ_PARTITION rosy_ring, CORE port 8488, run dir ring, world ring_fleet_real.world.
# Shipped line_follow defaults (arc off) + obstacle_mode path, ir_guard_enabled, site_floor_map_id map_v2_fleet.
#   setsid nohup bash ring_run.sh > ~/rosy_ring_ws/sim.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_ring_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/ring#' -e 's#d495_fleet_real.world#ring_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_ring.sh"
WS=$WS PORT=8488 ROS_DOMAIN_ID=92 GZ_PARTITION=rosy_ring exec bash "$E/run_sim_ring.sh" "$@"
