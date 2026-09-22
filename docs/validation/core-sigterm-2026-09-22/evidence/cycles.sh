#!/bin/bash
# usage: cycles.sh <label> <mode steady|startup> <count> <signal TERM|INT>
LABEL=$1; MODE=$2; COUNT=$3; SIG=${4:-TERM}; LO=${5:-0.2}; HI=${6:-1.5}
WS=/root/rosy_sigterm_ws
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/sigterm
OUTDIR=$D/out/$LABEL-$MODE-$SIG$([ $MODE = startup ] && echo -$LO-$HI); rm -rf $OUTDIR; mkdir -p $OUTDIR
source /opt/ros/jazzy/setup.bash; source $WS/install/setup.bash
export ROSY_ROBOT_NUMBER=1 ROS_DOMAIN_ID=43 ROS_LOCALHOST_ONLY=1
[ -n "$FH" ] && export PYTHONFAULTHANDLER=1
OUT=$OUTDIR/summary.txt
# CPU load: 6 busy loops for the duration
LOADPIDS=""
for i in 1 2 3 4 5 6; do python3 -c 'while True: pass' & LOADPIDS="$LOADPIDS $!"; done
echo "# $LABEL mode=$MODE signal=SIG$SIG count=$COUNT; startup window=${LO}-${HI}s; SIG to core node PID (child of ros2 run); fresh HOME per run; 6 busy-loop load procs" > $OUT
echo "# commit: $(cat $WS/COMMIT 2>/dev/null)  started $(date -Is)  loadavg: $(cat /proc/loadavg)" >> $OUT
for n in $(seq 1 $COUNT); do
  H=/root/rosy_sigterm_home/r$n; rm -rf $H; mkdir -p $H
  HOME=$H ros2 run core core > $H/console.log 2>&1 &
  W=$!
  NP=""
  for i in $(seq 1 400); do NP=$(pgrep -P $W | head -1); [ -n "$NP" ] && break; sleep 0.01; done
  T0=$(date +%s.%N)
  if [ "$MODE" = steady ]; then
    for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1)" = 200 ] && break; sleep 0.5; done
    DELAY=$(python3 -c "import random;print(round(random.uniform(0.5,3.0),2))")
  else
    DELAY=$(python3 -c "import random;print(round(random.uniform($LO,$HI),2))")
  fi
  sleep $DELAY
  T1=$(date +%s.%N)
  kill -$SIG $NP
  for i in $(seq 1 60); do kill -0 $NP 2>/dev/null || break; sleep 0.5; done
  ALIVE=$(kill -0 $NP 2>/dev/null && echo yes || echo no)
  [ $ALIVE = yes ] && kill -KILL $NP
  wait $W; RC=$?
  AT=$(python3 -c "print(round($T1-$T0,2))")
  PHASE=$(grep -q 'api server on' $H/console.log && echo after-api || (grep -q 'core up' $H/console.log && echo after-core-up || echo before-core-up))
  printf "run %2d: node %s sig@+%ss(after node spawn) phase=%s alive30s=%s exit=%s shutting_down=%s traceback=%s err=%s audit_last=%s port8080=%s\n" \
    $n $NP $AT $PHASE $ALIVE $RC "$(grep -c 'core shutting down' $H/console.log)" "$(grep -c Traceback $H/console.log)" \
    "$(grep -oE '(RCLError|Error|Exception): [^,]{0,60}' $H/console.log | tail -1 | tr ' ' '_')" \
    "$(tail -1 $H/.rosy/audit.jsonl 2>/dev/null | grep -o '"type":"[^"]*"' | head -1)" "$(ss -ltn | grep -c ':8080 ')" >> $OUT
  cp $H/console.log $OUTDIR/run$n-console.log
done
kill $LOADPIDS 2>/dev/null
echo "# leftover core processes: $(pgrep -f 'lib/core/core' | wc -l)  finished $(date -Is)" >> $OUT
echo "# exit-code tally: $(grep -o 'exit=[0-9]*' $OUT | sort | uniq -c | tr '\n' ' ')" >> $OUT
cat $OUT
