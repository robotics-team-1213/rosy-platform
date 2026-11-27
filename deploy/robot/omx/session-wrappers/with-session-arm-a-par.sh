#!/bin/bash
# start the arm session if none is running (the idle watchdog ends it after ~6 min), then run the given command
set -a; . ~/.config/rosy/omx-observation-bridge.env; set +a  # omx_incident reports to Fleet (D-971); before the tools env so its PYTHONPATH wins
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)  # the release's session-wrappers folder, found before the cd below
cd ~/rosy-test/omx-record-prep-20261019; . "$here/tools-env.sh"  # the release's tools (TOOLS_ROOT); the prep folder keeps only data
export ROSY_SESSION_T0=${ROSY_SESSION_T0:-$(date +%s)}; attempt=${ROSY_SESSION_ATTEMPT:-1}; wrapper_args=("$@")  # a retry re-runs this wrapper; T0 keeps the total wait
refuse() {  # $1 code hint, $2 the old REFUSED line: keep the line, add a JSON reason line, and try again only for a transient cause (session_refusal.py)
  echo "$2"
  out=$(~/rosy-omx/current-env/bin/python "$OMX/session_refusal.py" --arm arm_a --code "$1" --message "$2" --status chunk-io-a/chunk-status.jsonl --n0 "${n0:-0}" --log "${slog:-}" --bg-alive "${bg_alive:-0}" --attempt "$attempt" --t0 "$ROSY_SESSION_T0" --state-file chunk-io-a/live.json --state-file "${ROSY_OMX_MONITOR_STATE:-motor-health-current.json}" 2>/dev/null); rc=$?
  [ -n "$out" ] && echo "$out"
  if [ "$rc" -eq 10 ]; then ROSY_SESSION_ATTEMPT=$((attempt+1)) exec bash "$here/$(basename "${BASH_SOURCE[0]}")" "${wrapper_args[@]}"; fi
}
: # the per-arm lock (record_session --arm) keeps the arms apart
if ! { [ -p chunk-io-a/chunk-cmd ] && ~/rosy-omx/current-env/bin/python -c 'import os,sys; os.close(os.open(sys.argv[1], os.O_WRONLY|os.O_NONBLOCK))' chunk-io-a/chunk-cmd 2>/dev/null; }; then
  systemctl --user stop rosy-omx-observer@arm_a.service
  for _ in $(seq 1 25); do systemctl --user is-active --quiet rosy-omx-observer@arm_a.service || break; sleep 0.2; done
  sleep 0.2
  flock -n ~/rosy-omx/session-arm_a.lock true || { refuse lock_held "REFUSED: the arm session lock is held"; exit 2; }
  export ROSY_IDLE_OPEN_GRIP=${ROSY_IDLE_OPEN_GRIP:-56.0}  # idle fold opens empty jaws in place, then folds home (2026-11-27 user, chunk_runner_idle_open)
  export ROSY_CHUNK_TRACE=$HOME/rosy-test/omx-record-prep-20261019/trace-arm_a-$(date +%Y%m%d-%H%M%S).jsonl  # jitter_replay.py reads it (2026-11-04)
  STATUS=chunk-io-a/chunk-status.jsonl
  if [ -f "$STATUS" ] && [ "$(stat -c %s "$STATUS" 2>/dev/null || echo 0)" -gt 5242880 ]; then mv -f "$STATUS" "${STATUS}.1"; fi
  n0=$(wc -l < "$STATUS" 2>/dev/null || echo 0)
  slog=session-arm_a-$(date +%H%M%S).log
  (
    config=record-config.json
    if [ "${ROSY_BASELINE_RECOVERY_ARM:-}" = arm_a ]; then config=record-config-arm-a.json; fi
    ~/rosy-omx/current-env/bin/python "$OMX/record_session.py" --config "$config" --caps caps-arm-a-wrist400-20261109.json --arm arm_a --chunks "${ROSY_SESSION_CHUNKS:-chunks-topdown-guard-arma-closed49-20261103.json}" --io chunk-io-a --params cell-params-floor-1028.json --operating-profile arm-a-robot-profile.json </dev/null
    rc=$?
    # record_session exits 78 only after proving a pre-start refusal left the arm idle.
    if { [ "$rc" -eq 0 ] || [ "$rc" -eq 78 ]; } && flock -n ~/rosy-omx/session-arm_a.lock true; then
      ~/rosy-omx/current-env/bin/python "$OMX/observer_handoff.py" release arm_a
    fi
    exit "$rc"
  ) > "$slog" 2>&1 &
  bg_pid=$!
  for i in $(seq 1 90); do
    sleep 2
    if tail -n +$((n0+1)) chunk-io-a/chunk-status.jsonl 2>/dev/null | grep -q '"command": "start", "ok": true'; then break; fi
    if ! kill -0 $bg_pid 2>/dev/null; then break; fi
  done
  kill -0 $bg_pid 2>/dev/null && bg_alive=1  # still starting after the wait: a stuck session, never a second try
  tail -n +$((n0+1)) chunk-io-a/chunk-status.jsonl 2>/dev/null | grep -q '"command": "start", "ok": true' || { refuse start_failed "REFUSED: the arm session did not start"; exit 2; }
fi
export ROSY_SESSION_UP_S=$(( $(date +%s) - ROSY_SESSION_T0 )) ROSY_SESSION_ATTEMPTS=$attempt  # cell_policy_run reads these for its receipt
echo "session up"
exec "$@"
