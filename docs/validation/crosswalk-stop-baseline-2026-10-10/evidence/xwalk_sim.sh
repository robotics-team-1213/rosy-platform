#!/bin/bash
# D-573 (g) crosswalk baseline sim (model PC only; never the Windows laptop).
# Lap SIM 4's ring4_run.sh (D-495 run_sim.sh, shipped line_follow defaults + obstacle_mode path,
# ir_guard_enabled, site_floor_map_id map_v2_fleet) with its own isolation: workspace ~/rosy_xwalk_ws,
# ROS domain 61, GZ_PARTITION rosy_xwalk, CORE port 8661, run dir xwalk, world xwalk_fleet_real.world,
# and the launch in a systemd scope with MemoryMax=8G.
#   setsid nohup bash xwalk_sim.sh > ~/rosy_xwalk_ws/sim.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_xwalk_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/xwalk#' -e 's#d495_fleet_real.world#xwalk_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e '/bridge_enabled: $B/d' -e '/recovery_local_enabled: $RECOVERY/d' \
  -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  -e 's#^ros2 launch #systemd-run --user --scope -q -p MemoryMax=8G ros2 launch #' \
  "$E/run_sim.sh" > "$E/run_sim_xwalk.sh"
WS=$WS PORT=8661 ROS_DOMAIN_ID=61 GZ_PARTITION=rosy_xwalk exec bash "$E/run_sim_xwalk.sh" "$@"
