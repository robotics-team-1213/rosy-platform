#!/bin/bash
# D-476 expected-road bridge in Gazebo (model PC): one Pinky on the real-profile map_v2_fleet
# track in 'keep' mode. Adapted from d407-gazebo-stuck-recovery-2026-10-02/evidence/run_sim.sh.
# Runs in the foreground (start it inside tmux).
#
#   BRIDGE=0|1 ENFORCE=0|1 [RECOVERY=false] bash run_sim.sh [spawn_x:=.. ...]
#
# Sim-only CORE overlay (device defaults untouched): api_port, line_follow.recovery_local_enabled
# true (D-476 runs only inside the D-468 arbitration) and line_follow.bridge_enabled = BRIDGE.
# Body geometry and obstacle_mode path come from the pinky_pro robot package core.yaml (URDF
# nominal), as on the device.
#
# ENFORCE=0: stock launch (gz_sim map_v2_fleet_real.launch.py, use_sim_time). The sensor adapter is
#   unset = off, as on the device, so the D-468 motion proof (return_sensor_allowed) is always false.
# ENFORCE=1: control.sensor_adapter.mode enforce, launched through d476_real.launch.py (wall-clock
#   mode, see its docstring) with sim_wall_shims.py (restamped scan/odom/camera, synthetic IR/IMU).
WS=${WS:-$HOME/rosy_d476_ws}
PORT=${PORT:-8095}
BRIDGE=${BRIDGE:-0}
RECOVERY=${RECOVERY:-true}  # line_follow.recovery_local_enabled (D-468); false = pre-D-468 reference
ENFORCE=${ENFORCE:-0}
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
# CORE's Python deps (deploy/robot/pinky_pro/requirements-core.txt) live in a workspace-local
# target dir: the model PC's system python3 has no pip and ROS desktop lacks fastapi/pydantic.
#   uv pip install --python /usr/bin/python3 --target $WS/pydeps fastapi pydantic uvicorn websockets
export PYTHONPATH=$WS/pydeps:$PYTHONPATH
# The rosy.* namespace packages (contracts/motion etc.) are not colcon packages: add their src/.
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
YAML
if [ "$ENFORCE" = "1" ]; then
  cat >> "$RUN/core_overlay.yaml" <<'YAML'
control:
  sensor_adapter:
    mode: "enforce"
    parameters:
      lidar_use_tf: false   # TF is on sim stamps; use line_follow's 180 deg mount
YAML
fi
pkill -f "ros2 launch .*(map_v2_fleet_real|d476_real).launch.py"
pkill -f "gz sim.*map_v2_fleet_real.world"
pkill -f "$RUN/sim_jpeg_relay|sim_wall_shims"
sleep 2
tr -d '\r' < "$WS/src/rosy-platform/tools/sim_jpeg_relay.py" > "$RUN/sim_jpeg_relay.py"
if [ "$ENFORCE" = "1" ]; then
  ros2 launch "$HERE/d476_real.launch.py" camera_lane_mode:=keep \
    core_overlay:="$RUN/core_overlay.yaml" "$@" > "$RUN/launch.log" 2>&1 &
  LPID=$!
  python3 "$HERE/sim_wall_shims.py" > "$RUN/shims.log" 2>&1 &
  SIMT=false
else
  ros2 launch gz_sim map_v2_fleet_real.launch.py camera_lane_mode:=keep \
    core_overlay:="$RUN/core_overlay.yaml" "$@" > "$RUN/launch.log" 2>&1 &
  LPID=$!
  SIMT=true
fi
for i in $(seq 1 60); do sleep 2; ros2 topic list 2>/dev/null | grep -qx /camera/front && break; done
python3 "$RUN/sim_jpeg_relay.py" --ros-args -r camera/image_raw:=camera/front -p use_sim_time:=$SIMT \
  -r __node:=d476_jpeg_relay > "$RUN/relay.log" 2>&1 &
echo "sim up: CORE http://127.0.0.1:$PORT bridge=$B enforce=$ENFORCE (launch pid $LPID)"
wait $LPID
