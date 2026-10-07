#!/bin/bash
# B8 sim (model PC only): the D-495 run_sim.sh unchanged except its own ROS domain 78,
# GZ_PARTITION rosy_b8, CORE port 8098, run dir $WS/b8 and world file name, so a D-495/D-476
# session on the same host is not touched (and does not touch this one).
#   RECOVERY=false nohup bash b8_run.sh > ~/rosy_d495_ws/b8_sim.out 2>&1 &
WS=${WS:-$HOME/rosy_d495_ws}; E=$WS/evidence
sed -e 's#RUN=$WS/d495#RUN=$WS/b8#' -e 's#d495_fleet_real.world#b8_fleet_real.world#g' \
  "$E/run_sim.sh" > "$E/run_sim_b8.sh"
WS=$WS PORT=8098 ROS_DOMAIN_ID=78 GZ_PARTITION=rosy_b8 exec bash "$E/run_sim_b8.sh" "$@"
