#!/bin/bash
# Lap SIM diagnosis batch: lap2_batch.sh with ~/rosy_lapdiag_ws, domain 96, partition rosy_lapdiag,
# ports 8688 (CORE) / 8689 (Fleet). List: <name> <lap_trip args> per line.
L=$HOME/rosy_lapdiag_ws/src/rosy-platform/docs/validation/lane-trip-lap-sim2-2026-10-08/evidence
sed -e 's#rosy_lap2_ws#rosy_lapdiag_ws#' -e 's#ROS_DOMAIN_ID=91#ROS_DOMAIN_ID=96#' -e 's#GZ_PARTITION=rosy_lap2#GZ_PARTITION=rosy_lapdiag#' \
  -e 's#8388#8688#g' -e 's#8389#8689#g' "$L/lap2_batch.sh" > /tmp/lapdiag_batch.sh
exec bash /tmp/lapdiag_batch.sh "$@"
