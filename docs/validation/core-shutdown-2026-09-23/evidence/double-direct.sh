#!/bin/bash
# Double stop signal with a deliberately stuck shutdown, WITHOUT the ros2 run wrapper
# (the shipped unit execs the entry script). Expect: first signal -> shutdown hook runs
# and sticks; second signal -> immediate exit with core.main's STUCK_SHUTDOWN_EXIT_CODE.
# usage: double-direct.sh <ws> <label> [escalation selfkill|exit2]
WS=${1:-/root/rosy_shutdown_after}; LABEL=${2:-after}; MODE=${3:-exit2}
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/shutdown
N=$WS/src/core/core/core/node.py
M=$WS/src/core/core/core/main.py
cp $N /root/rosy_shutdown_diag/node.py.orig; cp $M /root/rosy_shutdown_diag/main.py.orig
python3 - $N <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('        self.get_logger().info("core shutting down")',
              '        self.get_logger().info("core shutting down")\n'
              '        import time; print("SLOW-SHUTDOWN: sleeping 60s", flush=True); time.sleep(60)', 1)
open(p, 'w').write(s)
PY
if [ "$MODE" = selfkill ]; then
  python3 - $M <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('        os._exit(STUCK_SHUTDOWN_EXIT_CODE)',
              '        os.kill(os.getpid(), signum)  # WSL-only: pre-review escalation', 1)
open(p, 'w').write(s)
PY
fi
source /opt/ros/jazzy/setup.bash; source $WS/install/setup.bash
export ROSY_ROBOT_NUMBER=1 ROS_DOMAIN_ID=44 ROS_LOCALHOST_ONLY=1
OUT=$D/out/double-direct-$LABEL; rm -rf $OUT; mkdir -p $OUT; S=$OUT/summary.txt
echo "# double signal, stuck shutdown (60 s sleep in node.shutdown, WSL-only patch), NO ros2 run wrapper" > $S
echo "# ws=$WS commit=$(cat $WS/COMMIT) escalation=$MODE  $(date -Is)" >> $S
for SIG in INT TERM; do for n in 1 2 3; do
  H=/root/rosy_shutdown_home/dd$SIG$n; rm -rf $H; mkdir -p $H/.rosy
  printf 'network:\n  api_port: 18480\n  api_host: 127.0.0.1\n' > $H/.rosy/rosy.yaml
  HOME=$H $WS/install/core/lib/core/core > $H/console.log 2>&1 &
  P=$!
  for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18480/api/v1)" = 200 ] && break; sleep 0.5; done
  sleep 1
  T0=$(date +%s.%N)
  kill -$SIG $P
  for i in $(seq 1 200); do grep -q SLOW-SHUTDOWN $H/console.log && break; sleep 0.1; done
  sleep 1
  A1=$(kill -0 $P 2>/dev/null && echo yes || echo no)
  kill -$SIG $P
  for i in $(seq 1 100); do kill -0 $P 2>/dev/null || break; sleep 0.1; done
  A2=$(kill -0 $P 2>/dev/null && echo yes || echo no); [ $A2 = yes ] && kill -KILL $P
  wait $P; RC=$?
  echo "SIG$SIG run $n: stuck after 1st=$A1, alive 10s after 2nd=$A2, exit=$RC (245-=signal death, 2=STUCK_SHUTDOWN_EXIT_CODE), first->exit $(python3 -c "print(round($(date +%s.%N)-$T0,2))")s, audit_last=$(tail -1 $H/.rosy/audit.jsonl 2>/dev/null | grep -o '\"type\":\"[^\"]*\"' | head -1), second_signal_line=$(grep -c 'second stop signal' $H/console.log)" >> $S
  cp $H/console.log $OUT/SIG$SIG-run$n-console.log
done; done
cp /root/rosy_shutdown_diag/node.py.orig $N; cp /root/rosy_shutdown_diag/main.py.orig $M
echo "# patches reverted: node SLOW lines=$(grep -c SLOW-SHUTDOWN $N) main selfkill lines=$(grep -c 'pre-review escalation' $M); leftover core: $(pgrep -f "$WS/install/core/lib/core/core" | wc -l)" >> $S
cat $S
