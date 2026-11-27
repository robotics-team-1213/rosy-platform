#!/bin/bash
set -a; . ~/.config/rosy/omx-observation-bridge.env; set +a
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)  # the release's session-wrappers folder, found before the cd below
cd ~/rosy-test/omx-record-prep-20261019; . "$here/tools-env.sh"  # the release's tools (TOOLS_ROOT); the prep folder keeps only data
if ! { [ -p chunk-io-s/chunk-cmd ] && ~/rosy-omx/current-env/bin/python -c 'import os,sys; os.close(os.open(sys.argv[1], os.O_WRONLY|os.O_NONBLOCK))' chunk-io-s/chunk-cmd 2>/dev/null; }; then
  systemctl --user stop rosy-omx-observer@arm_s.service
  for _ in $(seq 1 25); do systemctl --user is-active --quiet rosy-omx-observer@arm_s.service || break; sleep 0.2; done
  sleep 0.2
  flock -n ~/rosy-omx/session-arm_s.lock true || { echo "REFUSED: the arm session lock is held"; exit 2; }
  STATUS=chunk-io-s/chunk-status.jsonl
  export ROSY_IDLE_OPEN_GRIP=${ROSY_IDLE_OPEN_GRIP:-58.5}  # idle fold opens empty jaws in place, then folds home; v2.1 white jaws open 30 mm at 58.1 (2026-11-27 user)
  for attempt in 1 2 3; do
    export ROSY_CHUNK_TRACE=$HOME/rosy-test/omx-record-prep-20261019/trace-arm_s-$(date +%Y%m%d-%H%M%S).jsonl
    if [ -f "$STATUS" ] && [ "$(stat -c %s "$STATUS" 2>/dev/null || echo 0)" -gt 5242880 ]; then mv -f "$STATUS" "${STATUS}.1"; fi
    n0=$(wc -l < "$STATUS" 2>/dev/null || echo 0)
    (
      obs_dir=${ROSY_OBSERVATION_DIR:-}
      if [ -z "$obs_dir" ]; then
        obs_dir=$(systemctl --user show -p Environment --value rosy-omx-observation-bridge.service 2>/dev/null | tr ' ' '\n' | sed -n 's/^ROSY_OBSERVATION_DIR=//p' | tail -n 1)
      fi
      export ROSY_OBSERVATION_DIR=${obs_dir:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/rosy-observations}
      export ROSY_CHUNK_JOINT_TOPIC=/omx_commissioning/arm_s/joint_states
      ~/rosy-omx/current-env/bin/python "$OMX/record_session.py" --config record-config-arm-s-live.json --caps caps-arm-s-nowindup.json --arm arm_s --chunks "${ROSY_SESSION_CHUNKS:-chunks-arm-s-inplace-live.json}" --io chunk-io-s --params cell-params-floor-1028.json --operating-profile arm-s-robot-profile-live.json </dev/null
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
elif [ "${ROSY_SESSION_CHUNKS_STRICT:-}" = 1 ]; then
  # policy jobs only (folds and recovery reuse any session): the runner trusts its start library's grasp_pick,
  # so a policy job on another library would be refused later as a jaw_gate conflict
  running=$(pgrep -af '[r]ecord_session.py .*--io chunk-io-s' | sed -n 's/.* --chunks \([^ ]*\) .*/\1/p' | head -n 1)
  if [ -z "$running" ] || [ "$(realpath -m "$running")" != "$(realpath -m "${ROSY_SESSION_CHUNKS:-chunks-arm-s-inplace-live.json}")" ]; then
    echo "REFUSED: the running arm_s session started with ${running:-an unknown library}, this job needs ${ROSY_SESSION_CHUNKS:-chunks-arm-s-inplace-live.json}; wait for the idle fold to end the session, then retry"; exit 2
  fi
fi
echo "session up"
exec "$@"
