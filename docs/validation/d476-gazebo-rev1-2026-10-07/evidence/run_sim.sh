#!/bin/bash
# D-476 rev 1 Gazebo run (model PC): one Pinky on the 260919 real-profile track, keep mode,
# sim sensors (Gazebo IMU + IR floor rays, enforce floor proof). Adapted from
# ../../d476-gazebo-model-pc-2026-10-06/evidence/run_sim.sh (SIMSENS=1 path only).
# Foreground; start it inside its own tmux socket (tmux -L d476), the model PC is shared.
#
#   BRIDGE=0|1 [RECOVERY=false|true] [ENFORCE=1|0] [WORLD=/abs/world.sdf] bash run_sim.sh
#
# Sim-only CORE overlay (device defaults untouched): api_port, line_follow.recovery_local_enabled
# (default false here: rev 1 arms without D-468), bridge_enabled = BRIDGE and, as D-476 rev 1
# requires for an enabled bridge, ir_guard_enabled + bridge_site_no_dropoffs (the walled sim mat
# has no drop-off), then gz_sim config/sim_sensors_core.yaml (enforce, lidar/imu/ir).
# ENFORCE=0 leaves that fragment out (sensor adapter off, as on the device today): the bridge then
# runs on rev 1 path (b), bridge_site_no_dropoffs without the worker floor proof. The launch keeps
# sim_sensors:=true either way (IR for the guard).
# The launch is the installed map_v2_fleet_real.launch.py patched into $RUN (never the source):
#   - line_observer IR calibration black 100 / white 4000 so IR_LINE is a calibrated, fresh
#     observation (the IR guard is otherwise 'stale' = HOLD lane_guard_stale). sim_ir_floor
#     models floor/no-floor only (2000 on the mat), so IR_LINE never sees paint: the guard is
#     always 'clear' in this sim (no departure catch, no D-491 crosswalk false trigger).
#   - WORLD (optional) replaces the world file (paint-gap copy, make_gap_world.py).
WS=${WS:-$HOME/rosy_d476_ws}
PORT=${PORT:-8095}
BRIDGE=${BRIDGE:-0}
RECOVERY=${RECOVERY:-false}
WORLD=${WORLD:-}
ENFORCE=${ENFORCE:-1}
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
# CORE's Python deps (deploy/robot/pinky_pro/requirements-core.txt) in a workspace-local target.
export PYTHONPATH=$WS/pydeps:$PYTHONPATH
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH
done
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-76} GZ_PARTITION=${GZ_PARTITION:-rosy_d476}
RUN=$WS/d476; mkdir -p "$RUN"
SHARE=$(ros2 pkg prefix gz_sim)/share/gz_sim
sed "s/api_port: 8080/api_port: $PORT/" "$SHARE/config/map_v2_fleet_core.yaml" > "$RUN/core_overlay.yaml"
if [ "$BRIDGE" = "1" ]; then B=true; else B=false; fi
cat >> "$RUN/core_overlay.yaml" <<YAML
line_follow:
  recovery_local_enabled: $RECOVERY
  bridge_enabled: $B
  ir_guard_enabled: true
  bridge_site_no_dropoffs: true
YAML
[ "$ENFORCE" = "1" ] && cat "$SHARE/config/sim_sensors_core.yaml" >> "$RUN/core_overlay.yaml"
python3 - "$SHARE/launch/map_v2_fleet_real.launch.py" "$RUN/d476_rev1.launch.py" "$WORLD" <<'PY'
import sys
src = open(sys.argv[1]).read()
world = ('    world = os.path.join(\n        control_share, "map", "map_v2_fleet", "worlds", '
         '"map_v2_fleet_real.world")')
ground = '"camera_ground_source": "GAZEBO",'
assert world in src and ground in src, "map_v2_fleet_real.launch.py changed: re-check the patch"
if sys.argv[3]:
    src = src.replace(world, f'    world = {sys.argv[3]!r}')
src = src.replace(ground, ground + ' "ir_calibration_enabled": True, '
                  '"ir_black": [100.0, 100.0, 100.0], "ir_white": [4000.0, 4000.0, 4000.0],')
open(sys.argv[2], 'w').write(src)
PY
# Only this workspace's processes: a peer sim on the same PC uses other domains and paths.
pkill -f "$WS/(install|d476)/"; pkill -f "gz sim.*$WS/"
sleep 3
tr -d '\r' < "$WS/src/rosy-platform/tools/sim_jpeg_relay.py" > "$RUN/sim_jpeg_relay.py"
ros2 launch "$RUN/d476_rev1.launch.py" camera_lane_mode:=keep sim_sensors:=true \
  core_overlay:="$RUN/core_overlay.yaml" "$@" > "$RUN/launch.log" 2>&1 &
LPID=$!
for i in $(seq 1 60); do sleep 2; ros2 topic list 2>/dev/null | grep -qx /camera/front && break; done
python3 "$RUN/sim_jpeg_relay.py" --ros-args -r camera/image_raw:=camera/front -p use_sim_time:=true \
  -r __node:=d476_jpeg_relay > "$RUN/relay.log" 2>&1 &
echo "sim up: CORE http://127.0.0.1:$PORT bridge=$B recovery=$RECOVERY enforce=$ENFORCE world=${WORLD:-default} (launch pid $LPID)"
wait $LPID
