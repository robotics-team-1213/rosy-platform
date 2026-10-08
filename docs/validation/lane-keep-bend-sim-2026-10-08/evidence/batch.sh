#!/bin/bash
# Runs b9_go.sh for every line of batch.txt (<name> <probe args>), 300 s cap each.
cd ~/rosy_b9_ws; mkdir -p b9runs
while read -r name args; do
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> b9runs/batch.log
  eval timeout 300 bash b9/b9_go.sh $name $args >> b9runs/batch.log 2>&1
done < b9/batch.txt
echo BATCH_DONE >> b9runs/batch.log
