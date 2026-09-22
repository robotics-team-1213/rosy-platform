#!/bin/bash
# usage: lane.sh <ws> <outdir> <lane> <count> <signal TERM|INT>
# One lane: sequential steady-state runs of `ros2 run core core`, signal to the core node PID
# (child of the ros2 run wrapper) 0.5-3.0 s after GET /api/v1 answers 200.
# Each lane owns its own ROS_DOMAIN_ID (44+lane), API port (18480+lane) and HOME per run.
WS=$1; OUTDIR=$2; LANE=$3; COUNT=$4; SIG=${5:-TERM}
PORT=$((18480 + LANE))
source /opt/ros/jazzy/setup.bash; source $WS/install/setup.bash
export ROSY_ROBOT_NUMBER=1 ROS_DOMAIN_ID=$((44 + LANE)) ROS_LOCALHOST_ONLY=1 PYTHONFAULTHANDLER=1
[ -n "$SEGV_PRELOAD" ] && export LD_PRELOAD=$SEGV_PRELOAD
OUT=$OUTDIR/lane$LANE.txt
: > $OUT
for n in $(seq 1 $COUNT); do
  H=/root/rosy_shutdown_home/l$LANE-r$n; rm -rf $H; mkdir -p $H/.rosy
  printf 'network:\n  api_port: %s\n  api_host: 127.0.0.1\n' $PORT > $H/.rosy/rosy.yaml
  HOME=$H ros2 run core core > $H/console.log 2>&1 &
  W=$!
  NP=""
  for i in $(seq 1 400); do NP=$(pgrep -P $W | head -1); [ -n "$NP" ] && break; sleep 0.01; done
  for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/api/v1)" = 200 ] && break; sleep 0.5; done
  sleep $(python3 -c "import random;print(round(random.uniform(0.5,3.0),2))")
  T1=$(date +%s.%N)
  kill -$SIG $NP
  for i in $(seq 1 60); do kill -0 $NP 2>/dev/null || break; sleep 0.5; done
  ALIVE=$(kill -0 $NP 2>/dev/null && echo yes || echo no)
  [ $ALIVE = yes ] && kill -KILL $NP
  wait $W; RC=$?
  T2=$(date +%s.%N)
  C=$H/console.log
  printf "lane %d run %3d: exit=%s stop_s=%s alive30s=%s shutting_down=%s fatal=%s native=%s never_retrieved=%s traceback=%s audit_last=%s port=%s\n" \
    $LANE $n $RC "$(python3 -c "print(round($T2-$T1,2))")" $ALIVE "$(grep -c 'core shutting down' $C)" \
    "$(grep -c 'Fatal Python error' $C)" "$(grep -c NATIVE-CRASH $C)" "$(grep -c 'never retrieved' $C)" "$(grep -c Traceback $C)" \
    "$(tail -1 $H/.rosy/audit.jsonl 2>/dev/null | grep -o '"type":"[^"]*"' | head -1)" "$(ss -ltn | grep -c ":$PORT ")" >> $OUT
  if [ $RC != 0 ] || grep -q -e 'Fatal Python error' -e 'never retrieved' -e Traceback $C; then cp $C $OUTDIR/lane$LANE-run$n-console.log; fi
  rm -rf $H
done
