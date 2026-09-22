#!/bin/bash
# usage: campaign.sh <label> <ws> <lanes> <runs-per-lane> <signal> <busy-loops>
LABEL=$1; WS=$2; LANES=$3; COUNT=$4; SIG=${5:-TERM}; BUSY=${6:-4}
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/shutdown
OUTDIR=$D/out/$LABEL; rm -rf $OUTDIR; mkdir -p $OUTDIR
S=$OUTDIR/summary.txt
echo "# $LABEL ws=$WS commit=$(cat $WS/COMMIT) lanes=$LANES runs/lane=$COUNT signal=SIG$SIG busy-loops=$BUSY PYTHONFAULTHANDLER=1" > $S
echo "# started $(date -Is) loadavg $(cat /proc/loadavg)" >> $S
LOADPIDS=""
for i in $(seq 1 $BUSY); do python3 -c 'while True: pass' & LOADPIDS="$LOADPIDS $!"; done
PIDS=""
for l in $(seq 0 $((LANES-1))); do bash $D/lane.sh $WS $OUTDIR $l $COUNT $SIG & PIDS="$PIDS $!"; sleep 3; done
wait $PIDS
kill $LOADPIDS 2>/dev/null
cat $OUTDIR/lane*.txt >> $S
echo "# finished $(date -Is) loadavg $(cat /proc/loadavg); leftover core procs: $(pgrep -f "$WS/.*lib/core/core" | wc -l)" >> $S
echo "# exit tally: $(grep -o 'exit=[0-9]*' $S | sort | uniq -c | tr '\n' ' ')" >> $S
echo "# fatal(faulthandler) runs: $(grep -c 'fatal=[1-9]' $S)  never_retrieved runs: $(grep -c 'never_retrieved=[1-9]' $S)  audit!=system.shutdown: $(grep -vc 'audit_last="type":"system.shutdown"' <(grep '^lane' $S))" >> $S
tail -4 $S
