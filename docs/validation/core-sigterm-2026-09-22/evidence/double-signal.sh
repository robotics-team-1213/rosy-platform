# Double-signal escalation with a deliberately slow shutdown (WSL-only patch: 20 s sleep in node.shutdown)
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/sigterm
WS=/root/rosy_sigterm_ws
N=$WS/src/core/core/core/node.py
cp $N /root/node.py.orig
python3 - $N <<'PY'
import sys; p=sys.argv[1]; s=open(p).read()
s=s.replace('        self.get_logger().info("core shutting down")','        self.get_logger().info("core shutting down")\n        import time; print("SLOW-SHUTDOWN: sleeping 20s", flush=True); time.sleep(20)',1)
open(p,'w').write(s)
PY
source /opt/ros/jazzy/setup.bash; source $WS/install/setup.bash
export ROSY_ROBOT_NUMBER=1 ROS_DOMAIN_ID=43 ROS_LOCALHOST_ONLY=1
OUT=$D/out/review-double/summary.txt; mkdir -p $D/out/review-double
echo "# double signal, slow shutdown (node.shutdown sleeps 20 s, WSL-only patch), commit $(cat $WS/COMMIT)" > $OUT
for SIG in INT TERM; do for n in 1 2 3; do
  H=/root/rosy_sigterm_home/d$SIG$n; rm -rf $H; mkdir -p $H
  HOME=$H ros2 run core core > $H/console.log 2>&1 &
  W=$!
  NP=""; for i in $(seq 1 400); do NP=$(pgrep -P $W | head -1); [ -n "$NP" ] && break; sleep 0.01; done
  for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1)" = 200 ] && break; sleep 0.5; done
  sleep 1
  T0=$(date +%s.%N)
  kill -$SIG $NP
  for i in $(seq 1 100); do grep -q SLOW-SHUTDOWN $H/console.log && break; sleep 0.1; done
  sleep 1
  ALIVE1=$(kill -0 $NP 2>/dev/null && echo yes || echo no)
  kill -$SIG $NP
  for i in $(seq 1 100); do kill -0 $NP 2>/dev/null || break; sleep 0.1; done
  T1=$(date +%s.%N)
  ALIVE2=$(kill -0 $NP 2>/dev/null && echo yes || echo no); [ $ALIVE2 = yes ] && kill -KILL $NP
  wait $W; RC=$?
  echo "SIG$SIG run $n: alive after 1st signal (in slow shutdown)=$ALIVE1, alive 10s after 2nd=$ALIVE2, exit=$RC, first->exit $(python3 -c "print(round($T1-$T0,2))")s, audit_last=$(tail -1 $H/.rosy/audit.jsonl 2>/dev/null | grep -o '"type":"[^"]*"' | head -1), KeyboardInterrupt=$(grep -c KeyboardInterrupt $H/console.log), tail='$(tail -1 $H/console.log)'" >> $OUT
  cp $H/console.log $D/out/review-double/SIG$SIG-run$n-console.log
done; done
cp /root/node.py.orig $N
echo "# node.py restored: $(grep -c SLOW-SHUTDOWN $N) patch lines left; leftover core: $(pgrep -f 'lib/core/core' | wc -l)" >> $OUT
cat $OUT
