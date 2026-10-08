#!/bin/bash
# Lap SIM diagnosis (model PC only): lap2_run.sh with workspace ~/rosy_lapdiag_ws, domain 96,
# partition rosy_lapdiag, CORE port 8688. Same shipped-default layer as lap SIM 2.
#   systemd-run --user --scope -p MemoryMax=8G setsid nohup bash diag_run.sh > ~/rosy_lapdiag_ws/sim.out 2>&1 < /dev/null &
# The first attempt used 8488, which rosy_ring's CORE (domain 92) already held: check before starting.
ss -ltn | grep -qE ':86(88|89) ' && { echo "port 8688/8689 busy (another session): not starting"; exit 1; }
L=$HOME/rosy_lapdiag_ws/src/rosy-platform/docs/validation/lane-trip-lap-sim2-2026-10-08/evidence
sed -e 's#rosy_lap2_ws#rosy_lapdiag_ws#' -e 's#PORT=8388#PORT=8688#' -e 's#ROS_DOMAIN_ID=91#ROS_DOMAIN_ID=96#' \
  -e 's#GZ_PARTITION=rosy_lap2#GZ_PARTITION=rosy_lapdiag#' -e 's#run_sim_lap2.sh#run_sim_lapdiag.sh#g' \
  -e 's#RUN=$WS/lap2#RUN=$WS/lapdiag#' -e 's#lap2_fleet_real.world#lapdiag_fleet_real.world#g' "$L/lap2_run.sh" > /tmp/lapdiag_run.sh
exec bash /tmp/lapdiag_run.sh "$@"
