#!/bin/bash
# Runs b4_go.sh for every line of batch.txt (<name> <script> <probe args>), 300 s cap each.
cd ~/rosy_b4_ws; mkdir -p b4runs
while read -r name script args; do
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> b4runs/batch.log
  eval timeout 300 bash b4/b4_go.sh $name $script $args >> b4runs/batch.log 2>&1
done < ${1:-b4/batch.txt}
echo BATCH_DONE >> b4runs/batch.log
