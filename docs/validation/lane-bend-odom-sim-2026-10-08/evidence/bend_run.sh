#!/bin/bash
# Bend-pass SIM (model PC only): the B9 harness (b9_run.sh -> D-495 run_sim.sh) unchanged except
# its own workspace (~/rosy_bendodom_ws, built from feat/d507-bend-odom-pass), ROS domain 86,
# GZ_PARTITION rosy_bendodom, CORE port 8113, run dir $WS/bendodom and world file name, so the
# other sessions on this host (domains 78, 81) are not touched. Keeper gate off (no GATE): the
# product keeper, no CORE->perception channel.
#   RECOVERY=false setsid nohup bash bend_run.sh > ~/rosy_bendodom_ws/sim.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_bendodom_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/bendodom#' -e 's#d495_fleet_real.world#bendodom_fleet_real.world#g' \
  -e '/bridge_site_no_dropoffs/d' -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet#' \
  "$E/run_sim.sh" > "$E/run_sim_bendodom.sh"
WS=$WS PORT=8113 ROS_DOMAIN_ID=86 GZ_PARTITION=rosy_bendodom exec bash "$E/run_sim_bendodom.sh" "$@"
