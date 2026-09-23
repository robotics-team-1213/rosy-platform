#!/bin/bash
# systemd start/stop cycles for a WSL copy of deploy/robot/native/rosy-core.service.
# usage: sd.sh <variant new|old> <steady-cycles> <startup-delays...>
#   new = unit as committed (exec the core entry script)
#   old = same unit with the ExecStart of main (exec ros2 run core core)
# Private workspace /opt/rosy_sdtest/current (git archive of the branch, --merge-install),
# unit in /run/systemd/system (runtime only), ROS_DOMAIN_ID=44, ROS_LOCALHOST_ONLY=1.
VARIANT=$1; STEADY=$2; shift 2; DELAYS="$@"
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/shutdown
ROOTW=/opt/rosy_sdtest/current
U=rosy-core-sdtest.service
UF=/run/systemd/system/$U
STATE=/var/lib/rosy-sdtest
PORT=18490
OUT=$D/out/sd-$VARIANT; rm -rf $OUT; mkdir -p $OUT
S=$OUT/summary.txt

SRC_UNIT=$ROOTW/deploy/robot/native/rosy-core.service
sed -e "s#/opt/rosy/current#$ROOTW#g" \
    -e '/^Requires=/d' -e '/^After=/d' -e '/^PartOf=/d' -e '/^User=/d' -e '/^Group=/d' \
    -e '/^EnvironmentFile=/d' -e '/^ReadWritePaths=/d' -e '/^StateDirectory=/d' \
    -e '/^RuntimeDirectory=/d' -e '/^WantedBy=/d' -e '/^\[Install\]/d' \
    -e "s#^\[Service\]#[Service]\nEnvironment=ROS_DOMAIN_ID=44 ROS_LOCALHOST_ONLY=1 ROSY_ROBOT_NUMBER=1 ROSY_NAMESPACE=rosy_01 ROSY_RUNTIME_MODE=core ROSY_API_PORT=$PORT HOME=$STATE\nStateDirectory=rosy-sdtest\nReadWritePaths=$STATE#" \
    $SRC_UNIT > $UF
if [ "$VARIANT" = old ]; then
  sed -i "s#exec $ROOTW/install/lib/core/core --ros-args#exec ros2 run core core --ros-args#" $UF
fi
mkdir -p $STATE/.rosy
printf 'network:\n  api_port: %s\n  api_host: 127.0.0.1\n' $PORT > $STATE/.rosy/rosy.yaml
systemctl daemon-reload
cp $UF $OUT/unit-under-test.service
AUD=$STATE/.rosy/audit.jsonl

echo "# variant=$VARIANT unit=$UF commit=$(cat $ROOTW/COMMIT) started $(date -Is) loadavg $(cat /proc/loadavg)" > $S
echo "# ExecStart: $(grep ^ExecStart= $UF)" >> $S
echo "# $(grep -E '^(KillSignal|Restart|RestartSec|TimeoutStopSec)=' $UF | tr '\n' ' ')" >> $S

LOADPIDS=""
for i in 1 2 3 4; do python3 -c 'while True: pass' & LOADPIDS="$LOADPIDS $!"; done

record() {  # <label> <t0> <audit-lines-before>
  local show; show=$(systemctl show -p Result,ExecMainCode,ExecMainStatus,NRestarts,ActiveState $U | tr '\n' ' ')
  local newaudit; newaudit=$(tail -n +$(( $3 + 1 )) $AUD 2>/dev/null | grep -o '"type":"[^"]*"' | grep -E 'system\.(boot|shutdown)' | sed 's/"type"://' | tr -d '"' | tr '\n' ',')
  local leftover; leftover=$(pgrep -f "$ROOTW/install/lib/core/core" | wc -l)
  echo "$1: $show audit+=[$newaudit] port=$(ss -ltn | grep -c ":$PORT ") leftover_core=$leftover stop_s=$(python3 -c "print(round($(date +%s.%N)-$2,2))")" >> $S
}

for n in $(seq 1 $STEADY); do
  systemctl reset-failed $U 2>/dev/null
  A=$(wc -l < $AUD 2>/dev/null || echo 0)
  timeout 120 systemctl start $U; SRC=$?
  if [ $n = 1 ]; then MP=$(systemctl show -p MainPID --value $U); echo "# MainPID $MP: $(ps -o args= -p $MP | cut -c1-150)" >> $S; fi
  sleep $(python3 -c "import random;print(round(random.uniform(1.0,3.0),2))")
  T=$(date +%s.%N)
  systemctl stop $U
  record "steady $n (start rc=$SRC)" $T $A
done
for d in $DELAYS; do
  systemctl reset-failed $U 2>/dev/null
  A=$(wc -l < $AUD 2>/dev/null || echo 0)
  systemctl start --no-block $U
  sleep $d
  PH=$(systemctl show -p MainPID --value $U); PA=$(ps -o args= -p $PH 2>/dev/null | cut -c1-60)
  T=$(date +%s.%N)
  systemctl stop $U
  record "startup stop @${d}s (main: $PA)" $T $A
done
kill $LOADPIDS 2>/dev/null
journalctl -u $U --since "$(sed -n 's/.*started \([^ ]*\) .*/\1/p' $S | head -1 | sed 's/T/ /;s/+09:00//')" --no-pager -o short-iso > $OUT/journal.txt 2>&1
echo "# finished $(date -Is)" >> $S
echo "# Result tally: $(grep -o 'Result=[a-z-]*' $S | sort | uniq -c | tr '\n' ' ')" >> $S
cat $S
