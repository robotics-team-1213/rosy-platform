#!/usr/bin/env bash
# Run one command against the arm session, starting the session first if none is running.
#
# The session (record_session.py with its chunk runner) owns the safety moves: it folds the arm home and turns torque
# OFF when idle. 2026-10-31: it was started as a background job of the ssh command; the site PC then dropped off the
# network mid-carry, and a session tied to that shell may not outlive it. Here it starts in its own session (setsid,
# nohup, no terminal), so losing the caller never takes the safety moves with it.
#
#   OMX=<tools>/deploy/robot/omx OMX_SESSION_ARGS="--config record-config.json --caps caps.json --chunks ... --io chunk-io \
#     --params cell-params.json --operating-profile profile.json" omx_session.sh python3 $OMX/cell_auto_pick.py ...
#   omx_session.sh --status
set -euo pipefail
: "${OMX:?set OMX to the deploy/robot/omx directory of the installed tools}"
PY=${OMX_PYTHON:-$HOME/rosy-omx/current-env/bin/python}
IO=${OMX_IO:-chunk-io}
WAIT_S=${OMX_SESSION_WAIT_S:-180}
PID_FILE="$IO/session.pid"

running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

if [ "${1:-}" = "--status" ]; then
  running && echo "session running (pid $(cat "$PID_FILE"))" || echo "no session"
  exit 0
fi

if ! running; then
  : "${OMX_SESSION_ARGS:?set OMX_SESSION_ARGS to the record_session.py arguments for this site}"
  mkdir -p "$IO"
  before=$(wc -l < "$IO/chunk-status.jsonl" 2>/dev/null || echo 0)
  # shellcheck disable=SC2086  # the site's argument list is word-split on purpose
  setsid nohup "$PY" "$OMX/record_session.py" $OMX_SESSION_ARGS \
    > "session-$(date +%Y%m%d-%H%M%S).log" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  for _ in $(seq 1 "$WAIT_S"); do
    if tail -n +"$((before + 1))" "$IO/chunk-status.jsonl" 2>/dev/null | grep -q '"command": "start"'; then
      break
    fi
    running || { echo "session exited before it answered; see the newest session-*.log" >&2; exit 2; }
    sleep 1
  done
  tail -n +"$((before + 1))" "$IO/chunk-status.jsonl" 2>/dev/null | grep -q '"command": "start"' \
    || { echo "session did not answer within ${WAIT_S} s" >&2; exit 2; }
  echo "session up (pid $(cat "$PID_FILE"))" >&2
fi

[ "$#" -gt 0 ] && exec "$@"
