#!/bin/bash
# start the arm session if none is running (the idle watchdog ends it after ~6 min), then run the given command
set -a; . ~/.config/rosy/omx-observation-bridge.env; set +a  # omx_incident reports to Fleet (D-971); before the tools env so its PYTHONPATH wins
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)  # the release's session-wrappers folder, found before the cd below
cd ~/rosy-test/omx-record-prep-20261019; . "$here/tools-env.sh"  # the release's tools (TOOLS_ROOT); the prep folder keeps only data
mine=$(ps -eo cmd | grep -c "[r]ecord_session.py .*--chunks .*--io chunk-io-b ")
other=$(ps -eo cmd | grep "[r]ecord_session.py" | grep -vc -- "--io chunk-io-b ")
: # the per-arm lock (record_session --arm) keeps the arms apart
if [ "$mine" = "0" ]; then
  systemctl --user stop rosy-omx-observer@arm_b.service
  sleep 1
  flock -n ~/rosy-omx/session-arm_b.lock true || { echo "REFUSED: the arm session lock is held"; exit 2; }
  export ROSY_CHUNK_TRACE=$HOME/rosy-test/omx-record-prep-20261019/trace-arm_b-$(date +%Y%m%d-%H%M%S).jsonl  # jitter_replay.py reads it (2026-11-04)
  n0=$(wc -l < chunk-io-b/chunk-status.jsonl 2>/dev/null || echo 0)
  ~/rosy-omx/current-env/bin/python $OMX/record_session.py --config record-config-arm-b.json --caps caps-arm-b-wrist400-20261103.json --arm arm_b --chunks "${ROSY_SESSION_CHUNKS:-chunks-topdown-guard-armb-v21.json}" --io chunk-io-b --params cell-params-floor-1028.json --operating-profile arm-b-robot-profile.json > session-$ARM-$(date +%H%M%S).log 2>&1 &
  for i in $(seq 1 90); do sleep 2; tail -n +$((n0+1)) chunk-io-b/chunk-status.jsonl 2>/dev/null | grep -q '"command": "start", "ok": true' && break; done
  tail -n +$((n0+1)) chunk-io-b/chunk-status.jsonl 2>/dev/null | grep -q '"command": "start", "ok": true' || { echo "REFUSED: the arm session did not start"; exit 2; }
fi
echo "session up"
exec "$@"
