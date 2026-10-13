#!/bin/bash
cd ~/rosy_ring4_ws
setsid nohup bash ring4_run.sh > simI.out 2>&1 < /dev/null &
sleep 50
OUTD=runs_lap4i bash ring4_batch.sh lap4_batch.txt > batch_lap4i.out 2>&1
OUTD=runs_ne4i bash ring4_batch.sh ne4_batch.txt > batch_ne4i.out 2>&1
echo ALL_DONE > runI.done
