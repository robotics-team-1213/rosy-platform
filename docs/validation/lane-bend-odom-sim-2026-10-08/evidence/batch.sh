#!/bin/bash
# One bend_probe.py run per line of batch.txt (<name> <probe args>), 240 s cap each, into
# ~/rosy_bendodom_ws/runs/<name>/ (log/cmd/keep/actions/events.jsonl, summary.json).
WS=$HOME/rosy_bendodom_ws; H=$WS/src/rosy-platform/docs/validation/lane-bend-odom-sim-2026-10-08/evidence
cd "$WS" || exit 1
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$PYTHONPATH ROS_DOMAIN_ID=86 GZ_PARTITION=rosy_bendodom
mkdir -p runs
while read -r name args; do
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> runs/batch.log
  rm -rf "runs/$name"; mkdir -p "runs/$name"
  eval timeout 240 python3 "$H/bend_probe.py" --out "runs/$name" $args > "runs/$name/probe.out" 2>&1
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result'), d.get('error'), d.get('final_to_sw_node_m'))" \
    "runs/$name/summary.json" >> runs/batch.log 2>&1
done < "${1:-$H/batch.txt}"
echo BATCH_DONE >> runs/batch.log
