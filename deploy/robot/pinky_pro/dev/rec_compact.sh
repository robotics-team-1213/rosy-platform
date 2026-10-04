#!/usr/bin/env bash
# Bench-only compact recorder (no service or install change). Same session.json schema
# (rosy.recording.session/1) and folder layout as ~/rosy_rec.sh, but records the JPEG
# camera/front/compressed from jpeg_relay.py next to this script instead of raw camera/front.
#   rec_compact.sh start <reason>   relay + ros2 bag (mcap, zstd_fast, 30 s splits)
#   rec_compact.sh stop             SIGTERM recorder and relay, ended_at written
#   rec_compact.sh status
# Env: REC_ROOT (default ~/recordings), REC_STATE, JPEG_QUALITY (85), JPEG_MAX_FPS (0 = all).
# Test seams: RUNTIME_ENV, ROS_SETUP, REC_START_WAIT (seconds the new processes must survive), PROC_ROOT.

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${REC_ROOT:-$HOME/recordings}"
STATE="${REC_STATE:-$HOME/.rosy_rec_compact_current}"
RUNTIME_ENV="${RUNTIME_ENV:-/etc/rosy/runtime.env}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
PROC_ROOT="${PROC_ROOT:-/proc}"
RELAY_MARK="jpeg_relay.py"
BAG_MARK="bag record"
TOPICS=(camera/front/compressed cmd_vel line/observation perception/learned/shadow odom scan imu_raw joint_states)
mkdir -p "$ROOT"
env_ros() {
  unset ROSY_NAMESPACE
  eval "$(sudo -n grep -E '^(ROS_DOMAIN_ID|CYCLONEDDS_URI|ROSY_NAMESPACE|RMW_IMPLEMENTATION|ROS_AUTOMATIC_DISCOVERY_RANGE)=' "$RUNTIME_ENV" | sed 's/^/export /')"
  # shellcheck disable=SC1090
  source "$ROS_SETUP"
}
meta() {  # meta <folder> <python statement updating d>; values come in via REC_* env vars only
  python3 - "$1" "$2" <<'PY'
import json, os, sys
from datetime import datetime, timezone
p = os.path.join(sys.argv[1], "session.json"); d = json.load(open(p)) if os.path.exists(p) else {}
now = datetime.now(timezone.utc).isoformat()
env = os.environ.get
exec(sys.argv[2])
t = p + ".tmp"; f = open(t, "w"); json.dump(d, f, indent=2); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(t, p)
PY
}
_proc_state() {  # _proc_state <pid>: the scheduler state letter, or nothing (gone)
  # 상태는 커널의 진짜 /proc 에서만 읽는다 — PROC_ROOT 는 cmdline 신원의 시험 이음새다
  # (2026-10-02: 가짜 PROC_ROOT 에 stat 이 없어 좀비 판정이 무효화됐다).
  local line
  line=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
  # comm 은 공백·괄호를 포함할 수 있어 마지막 ") " 뒤가 상태 문자다.
  printf '%s' "${line##*) }" | cut -c1
}
alive() {  # alive <pid>: SIGKILL 로도 지워지지 않는 좀비는 죽은 것이다
  kill -0 "$1" 2>/dev/null || return 1
  [ "$(_proc_state "$1")" != "Z" ]
}
ours() {  # ours <pid> <mark>: alive AND its cmdline contains mark (a PID reused after a reboot is not ours)
  [ -n "$1" ] && alive "$1" && [ -r "$PROC_ROOT/$1/cmdline" ] \
    && tr '\0' ' ' < "$PROC_ROOT/$1/cmdline" | grep -qF -- "$2"
}
stop_pid() {  # stop_pid <pid> <seconds>: SIGTERM, wait, SIGKILL; returns 1 if it is still alive
  alive "$1" || return 0
  kill -TERM "$1" 2>/dev/null
  for _ in $(seq 1 "$2"); do alive "$1" || return 0; sleep 1; done
  kill -KILL "$1" 2>/dev/null; sleep 1
  alive "$1"
}
case "${1:-status}" in
  start)
    if [ -f "$STATE" ]; then
      read -r old_bpid old_rpid old_folder < "$STATE"
      if ours "$old_bpid" "$BAG_MARK"; then echo "already recording: $old_folder"; exit 1; fi
      # Stale state: the recorder is gone, so a leftover relay must not run twice.
      if ours "$old_rpid" "$RELAY_MARK"; then
        stop_pid "$old_rpid" 5 || { echo "stale relay $old_rpid did not exit"; exit 1; }
      fi
      rm -f "$STATE"
    fi
    env_ros
    if [ -z "${ROSY_NAMESPACE:-}" ]; then echo "ROSY_NAMESPACE is empty in $RUNTIME_ENV; refusing to record"; exit 1; fi
    dev="$(hostname | sed 's/[^A-Za-z0-9_-]/_/g')"
    folder="$ROOT/$(date -u +%Y%m%dT%H%M%SZ)_$dev"
    mkdir -p "$folder"
    ns="/${ROSY_NAMESPACE}"
    REC_DEV="$dev" REC_REASON="${2:-pilot-teleop}" REC_TOPICS="${TOPICS[*]}" meta "$folder" \
      "d.update(schema='rosy.recording.session/1', device=env('REC_DEV'), camera_profile_revision=None, model_revision=None, task_id=None, reason=env('REC_REASON'), started_at=now, ended_at=None, harvested=False, topics=env('REC_TOPICS').split())"
    setsid nohup python3 "$HERE/jpeg_relay.py" --ns "$ns" --quality "${JPEG_QUALITY:-85}" --max-fps "${JPEG_MAX_FPS:-0}" \
      > "$folder/relay.log" 2>&1 < /dev/null &
    rpid=$!
    args=(); for t in "${TOPICS[@]}"; do args+=("$ns/$t"); done
    setsid nohup ros2 bag record --storage mcap --storage-preset-profile zstd_fast --max-bag-duration 30 \
      -o "$folder/bag" "${args[@]}" > "$folder/record.log" 2>&1 < /dev/null &
    bpid=$!
    echo "$bpid $rpid $folder" > "$STATE"
    # Both must stay alive for the whole window; poll so an early exit is caught as soon as it happens.
    deadline=$((SECONDS + ${REC_START_WAIT:-3}))
    while :; do
      if ! alive "$bpid" || ! alive "$rpid"; then
        # Confirm disappearance once: a process visibility/exec transition
        # must not produce FAILED () while both children are actually alive.
        sleep 0.2
        why=""
        alive "$bpid" || why="recorder exited"
        alive "$rpid" || why="${why:+$why; }relay exited"
        [ -n "$why" ] && break
      fi
      [ "$SECONDS" -ge "$deadline" ] && { echo "recording: $folder"; exit 0; }
      sleep 0.2
    done
    echo "FAILED ($why):"; tail -n 5 "$folder/record.log" "$folder/relay.log"
    stop_pid "$bpid" 10; stop_pid "$rpid" 5
    REC_FAILURE="start failed: $why" meta "$folder" "d['ended_at'] = now; d['failure'] = env('REC_FAILURE')"
    rm -f "$STATE"
    exit 1
    ;;
  stop)
    [ -f "$STATE" ] || { echo "not recording"; exit 0; }
    read -r bpid rpid folder < "$STATE"
    # Background jobs of a non-interactive shell ignore SIGINT; rosbag2 and rclpy close cleanly on SIGTERM.
    # No SIGKILL for the recorder: a killed bag loses its footer, so wait and report instead.
    if ours "$bpid" "$BAG_MARK"; then
      kill -TERM "$bpid"
      for _ in $(seq 1 30); do alive "$bpid" || break; sleep 1; done
      alive "$bpid" && { echo "recorder $bpid did not exit; not marking ended"; exit 1; }
    fi
    if ours "$rpid" "$RELAY_MARK"; then stop_pid "$rpid" 10 || echo "relay $rpid did not exit"; fi
    meta "$folder" "d['ended_at'] = now"
    rm -f "$STATE"
    echo "stopped: $folder ($(du -sh "$folder" | cut -f1))"; ls "$folder/bag" 2>/dev/null | head
    ;;
  status)
    if [ -f "$STATE" ]; then read -r bpid rpid folder < "$STATE"; ours "$bpid" "$BAG_MARK" && echo "recording $folder $(du -sh "$folder" | cut -f1)" || echo "stale state $folder"; else echo "idle"; fi
    ls -1 "$ROOT" | tail -n 5; df -h "$ROOT" | tail -n 1
    ;;
esac
