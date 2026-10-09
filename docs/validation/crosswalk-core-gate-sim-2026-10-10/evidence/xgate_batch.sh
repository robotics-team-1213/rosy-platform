#!/bin/bash
# D-573 (c) gate-on batch: the baseline's xwalk_batch.sh on domain 63 / CORE 8663 / Fleet 8664.
WS=${WS:-$HOME/rosy_xgate_ws}
B=$WS/src/rosy-platform/docs/validation/crosswalk-stop-baseline-2026-10-10/evidence
X=$(cd "$(dirname "$0")" && pwd)
sed -e 's#ROS_DOMAIN_ID=61#ROS_DOMAIN_ID=63#' -e 's#rosy_xwalk#rosy_xgate#g' -e 's#8662#8664#g' -e 's#8661#8663#g' \
  -e 's#--ped "$ped"#--ped "$ped" --base http://127.0.0.1:8663 --fleet http://127.0.0.1:8664#' \
  -e 's#X=$(cd "$(dirname "$0")" \&\& pwd)#X='"$B"'#' "$B/xwalk_batch.sh" > "$X/xgate_batch_run.sh"
WS=$WS exec bash "$X/xgate_batch_run.sh" "$@"
