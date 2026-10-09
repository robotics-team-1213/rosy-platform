#!/bin/bash
# B4 sim (model PC only): the D-495 run_sim.sh unchanged except its own workspace (~/rosy_b4_ws,
# built from fix/d422-memory-outside-body), ROS domain 80, GZ_PARTITION rosy_b4, CORE port 8100,
# run dir $WS/b4 and world file name, so peer sessions on this host (B9: 79/rosy_b9/8099) are untouched.
#   RECOVERY=false setsid nohup bash b4/b4_run.sh > ~/rosy_b4_ws/b4_sim.out 2>&1 < /dev/null &
WS=${WS:-$HOME/rosy_b4_ws}
E=$WS/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/b4#' -e 's#d495_fleet_real.world#b4_fleet_real.world#g' \
  "$E/run_sim.sh" > "$WS/b4/run_sim_b4.sh"
cp "$E/d495_real.launch.py" "$E/d495_sim_aux.py" "$WS/b4/" 2>/dev/null
sed -i -e "s#HERE=.*#HERE=$E#"   -e 's#junction_turn_site_accepted: $S#site_floor_map_id: map_v2_fleet_real#'   -e '/bridge_site_no_dropoffs: true/d' "$WS/b4/run_sim_b4.sh"   # D-507 9 replaced both keys
WS=$WS PORT=8100 ROS_DOMAIN_ID=80 GZ_PARTITION=rosy_b4 exec bash "$WS/b4/run_sim_b4.sh" "$@"
