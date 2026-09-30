#!/usr/bin/env bash
# Bench-only compact recorder (no service or install change). Same session.json schema
# (rosy.recording.session/1) and folder layout as ~/rosy_rec.sh, but records the JPEG
# camera/front/compressed from jpeg_relay.py next to this script instead of raw camera/front.
#   rec_compact.sh start <reason>   relay + ros2 bag (mcap, zstd_fast, 30 s splits)
#   rec_compact.sh stop             SIGTERM recorder and relay, ended_at written
#   rec_compact.sh status
# Env: REC_ROOT (default ~/recordings), REC_STATE, JPEG_QUALITY (85), JPEG_MAX_FPS (0 = all).

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${REC_ROOT:-$HOME/recordings}"
STATE="${REC_STATE:-$HOME/.rosy_rec_compact_current}"
TOPICS=(camera/front/compressed cmd_vel line/observation perception/learned/shadow odom scan imu_raw joint_states)
mkdir -p "$ROOT"
env_ros() {
  eval "$(sudo -n grep -E '^(ROS_DOMAIN_ID|CYCLONEDDS_URI|ROSY_NAMESPACE|RMW_IMPLEMENTATION|ROS_AUTOMATIC_DISCOVERY_RANGE)=' /etc/rosy/runtime.env | sed 's/^/export /')"
  # shellcheck disable=SC1091
  source /opt/ros/jazzy/setup.bash
}
meta() {  # meta <folder> <python expr updating d>
  python3 - "$1" "$2" <<'PY'
import json, os, sys
from datetime import datetime, timezone
p = os.path.join(sys.argv[1], "session.json"); d = json.load(open(p)) if os.path.exists(p) else {}
now = datetime.now(timezone.utc).isoformat()
exec(sys.argv[2])
t = p + ".tmp"; f = open(t, "w"); json.dump(d, f, indent=2); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(t, p)
PY
}
case "${1:-status}" in
  start)
    if [ -f "$STATE" ] && kill -0 "$(cut -d' ' -f1 "$STATE")" 2>/dev/null; then echo "already recording: $(cut -d' ' -f3 "$STATE")"; exit 1; fi
    reason="${2:-pilot-teleop}"
    env_ros
    dev="$(hostname | sed 's/[^A-Za-z0-9_-]/_/g')"
    folder="$ROOT/$(date -u +%Y%m%dT%H%M%SZ)_$dev"
    mkdir -p "$folder"
    ns="/${ROSY_NAMESPACE}"
    topic_list="$(printf "'%s'," "${TOPICS[@]}")"
    meta "$folder" "d.update(schema='rosy.recording.session/1', device='$dev', camera_profile_revision=None, model_revision=None, task_id=None, reason='$reason', started_at=now, ended_at=None, harvested=False, topics=[${topic_list%,}])"
    setsid nohup python3 "$HERE/jpeg_relay.py" --ns "$ns" --quality "${JPEG_QUALITY:-85}" --max-fps "${JPEG_MAX_FPS:-0}" \
      > "$folder/relay.log" 2>&1 < /dev/null &
    rpid=$!
    args=(); for t in "${TOPICS[@]}"; do args+=("$ns/$t"); done
    setsid nohup ros2 bag record --storage mcap --storage-preset-profile zstd_fast --max-bag-duration 30 \
      -o "$folder/bag" "${args[@]}" > "$folder/record.log" 2>&1 < /dev/null &
    bpid=$!
    echo "$bpid $rpid $folder" > "$STATE"
    sleep 3
    if kill -0 "$bpid" 2>/dev/null && kill -0 "$rpid" 2>/dev/null; then echo "recording: $folder"
    else echo "FAILED:"; tail -5 "$folder/record.log" "$folder/relay.log"; kill -TERM "$bpid" "$rpid" 2>/dev/null; rm -f "$STATE"; exit 1; fi
    ;;
  stop)
    [ -f "$STATE" ] || { echo "not recording"; exit 0; }
    read -r bpid rpid folder < "$STATE"
    # Background jobs of a non-interactive shell ignore SIGINT; rosbag2 and rclpy close cleanly on SIGTERM.
    # The pattern starts with the interpreter path so it never matches this shell's own command line.
    pat="^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 bag record .*$folder/bag"
    pkill -TERM -f "$pat"
    for _ in $(seq 1 30); do pgrep -f "$pat" >/dev/null || break; sleep 1; done
    pgrep -f "$pat" >/dev/null && { echo "recorder did not exit; not marking ended"; exit 1; }
    kill -TERM "$rpid" 2>/dev/null
    for _ in $(seq 1 10); do kill -0 "$rpid" 2>/dev/null || break; sleep 1; done
    kill -0 "$rpid" 2>/dev/null && kill -KILL "$rpid"
    meta "$folder" "d['ended_at'] = now"
    rm -f "$STATE"
    echo "stopped: $folder ($(du -sh "$folder" | cut -f1))"; ls "$folder/bag" | head
    ;;
  status)
    if [ -f "$STATE" ]; then read -r bpid rpid folder < "$STATE"; kill -0 "$bpid" 2>/dev/null && echo "recording $folder $(du -sh "$folder" | cut -f1)" || echo "stale state $folder"; else echo "idle"; fi
    ls -1 "$ROOT" | tail -5; df -h "$ROOT" | tail -1
    ;;
esac
