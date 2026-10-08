#!/bin/bash
# D-517 M5 headless batch on the model PC; each run single-threaded under a memory cap.
cd ~/rosy-test/src/d517-m5/docs/validation/d517-m5-loop-sim-2026-10-08/evidence || exit 1
O=~/d517m5/runs; rm -rf $O; mkdir -p $O
run() { n=$1; shift; mkdir -p $O/$n; systemd-run --user --scope -q -p MemoryMax=1G ~/rosy-test/venv/bin/python -W ignore m5_loop.py "$@" --out $O/$n > $O/$n/stdout.txt 2>&1; echo "$n exit=$?" >> $O/done.txt; }
run two_30min --robots a:start_n:0.10 b:start_s:0.08 --minutes 30 &
run three_30min --robots a:start_n:0.10 b:start_s:0.08 c:east@0.3:0.09 --minutes 30 &
run four_refused --robots a:start_n:0.10 b:start_s:0.08 c:east@0.3:0.09 d:west@0.3:0.09 --minutes 1 &
run convoy_15min --robots a:start_n:0.08 b:follow_a:0.10 --minutes 15 &
run stuck_freeze --robots a:start_n:0.10 b:east@0.3:0.10 --freeze a:20:60 --minutes 4 &
run pose_loss --robots a:start_n:0.10 b:east@0.3:0.10 --pose-loss a:20:45 --minutes 4 &
run two_no_authority --robots a:start_n:0.08 b:east@0.3:0.10 --authority 0 --minutes 4 &
wait
echo ALL_DONE >> $O/done.txt
