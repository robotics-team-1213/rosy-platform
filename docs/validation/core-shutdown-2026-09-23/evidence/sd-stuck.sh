#!/bin/bash
# systemd: a stuck shutdown cut short by a second stop signal must stay a FAILURE,
# while an ordinary systemctl stop stays a success. Runs against the same unit copy
# as sd.sh, with a WSL-only 60 s sleep patched into the installed node.shutdown.
# usage: sd-stuck.sh <label> <escalation exit2|selfkill>
LABEL=$1; MODE=${2:-exit2}
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/shutdown
ROOTW=/opt/rosy_sdtest/current
U=rosy-core-sdtest.service
STATE=/var/lib/rosy-sdtest
PORT=18490
SITE=$(ls -d $ROOTW/install/lib/python3*/site-packages)
N=$SITE/core/node.py; M=$SITE/core/main.py
OUT=$D/out/sd-stuck-$LABEL; rm -rf $OUT; mkdir -p $OUT; S=$OUT/summary.txt
cp $N $OUT/node.py.orig; cp $M $OUT/main.py.orig
python3 - $N <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('        self.get_logger().info("core shutting down")',
              '        self.get_logger().info("core shutting down")\n'
              '        import time, sys; print("SLOW-SHUTDOWN: sleeping 60s", file=sys.stderr, flush=True); time.sleep(60)', 1)
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
echo "# $U stuck-shutdown case, escalation=$MODE, commit=$(cat $ROOTW/COMMIT)  $(date -Is)" > $S
echo "# ExecStart: $(grep ^ExecStart= /run/systemd/system/$U)" >> $S
echo "# node.shutdown patched with a 60 s sleep (> TimeoutStopSec=15) to wedge the stop" >> $S
for n in 1 2; do
  systemctl reset-failed $U 2>/dev/null
  timeout 180 systemctl start $U; SRC=$?
  MP=$(systemctl show -p MainPID --value $U)
  sleep 1
  T0=$(date +%s.%N)
  timeout 60 systemctl stop $U &
  STOPJOB=$!
  for i in $(seq 1 300); do journalctl -u $U --since "-2min" --no-pager | grep -q SLOW-SHUTDOWN && break; sleep 0.1; done
  sleep 1
  ALIVE=$(kill -0 $MP 2>/dev/null && echo yes || echo no)
  systemctl kill -s SIGINT $U            # operator's second stop signal
  wait $STOPJOB
  echo "run $n (start rc=$SRC, MainPID $MP, stuck at stop=$ALIVE): $(systemctl show -p Result,ExecMainCode,ExecMainStatus,NRestarts,ActiveState $U | tr '\n' ' ') stop_s=$(python3 -c "print(round($(date +%s.%N)-$T0,2))") audit_last=$(tail -1 $STATE/.rosy/audit.jsonl 2>/dev/null | grep -o '\"type\":\"[^\"]*\"' | head -1)" >> $S
done
journalctl -u $U --since "-10min" --no-pager -o short-iso > $OUT/journal.txt
cp $OUT/node.py.orig $N; cp $OUT/main.py.orig $M
systemctl reset-failed $U 2>/dev/null
echo "# patches reverted: SLOW lines=$(grep -c SLOW-SHUTDOWN $N) selfkill lines=$(grep -c 'pre-review escalation' $M)" >> $S
cat $S
