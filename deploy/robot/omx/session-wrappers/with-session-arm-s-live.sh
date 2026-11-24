#!/bin/bash
set -a; . ~/.config/rosy/omx-observation-bridge.env; set +a
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)  # the release's session-wrappers folder, found before the cd below
cd ~/rosy-test/omx-record-prep-20261019; . "$here/tools-env.sh"  # the release's tools (TOOLS_ROOT); the prep folder keeps only data
if ! { [ -p chunk-io-s/chunk-cmd ] && ~/rosy-omx/current-env/bin/python -c 'import os,sys; os.close(os.open(sys.argv[1], os.O_WRONLY|os.O_NONBLOCK))' chunk-io-s/chunk-cmd 2>/dev/null; }; then
  systemctl --user stop rosy-omx-observer@arm_s.service
  for _ in $(seq 1 25); do systemctl --user is-active --quiet rosy-omx-observer@arm_s.service || break; sleep 0.2; done
  sleep 0.2
  flock -n ~/rosy-omx/session-arm_s.lock true || { echo "REFUSED: the arm session lock is held"; exit 2; }
  for attempt in 1 2 3; do
    export ROSY_CHUNK_TRACE=$HOME/rosy-test/omx-record-prep-20261019/trace-arm_s-$(date +%Y%m%d-%H%M%S).jsonl
    n0=$(wc -l < chunk-io-s/chunk-status.jsonl 2>/dev/null || echo 0)
    (
      ~/rosy-omx/current-env/bin/python "$OMX/record_session.py" --config record-config-arm-s-live.json --caps caps-arm-s-nowindup.json --arm arm_s --chunks chunks-arm-s-inplace-live.json --io chunk-io-s --params cell-params-floor-1028.json --operating-profile arm-s-robot-profile-live.json </dev/null
      rc=$?
      if [ "$rc" -eq 0 ] && flock -n ~/rosy-omx/session-arm_s.lock true; then
        ~/rosy-omx/current-env/bin/python "$OMX/observer_handoff.py" release arm_s
      fi
      exit "$rc"
    ) > session-arm_s-$(date +%H%M%S).log 2>&1 &
    bg_pid=$!
    for i in $(seq 1 40); do
      sleep 1
      if tail -n +$((n0+1)) chunk-io-s/chunk-status.jsonl 2>/dev/null | grep -q '"command": "start", "ok": true'; then break 2; fi
      if ! kill -0 $bg_pid 2>/dev/null; then break; fi
    done
    sleep 2
  done
  tail -n +$((n0+1)) chunk-io-s/chunk-status.jsonl 2>/dev/null | grep -q '"command": "start", "ok": true' || { echo "REFUSED: the arm session did not start"; exit 2; }
fi
echo "session up"
exec "$@"
