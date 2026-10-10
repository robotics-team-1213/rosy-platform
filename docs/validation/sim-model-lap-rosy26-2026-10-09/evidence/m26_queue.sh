#!/bin/bash
# sequential runs: lines "NAME MODEL EVERY_N COMP LAT_MS ARC"
cd ~/rosy_m26_ws
while read -r name model n comp lat arc; do
  [ -z "$name" ] && continue
  echo "=== $name $(date +%T)" >> queue.log
  ARC=$arc bash m26_one.sh "$name" "$model" "$n" "$comp" "$lat" >> queue.log 2>&1
  cat "runs/$name/result.txt" >> queue.log
done < "$1"
echo QUEUE_DONE >> queue.log
