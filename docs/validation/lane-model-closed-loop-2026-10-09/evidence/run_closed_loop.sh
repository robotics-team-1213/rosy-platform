#!/bin/bash
# Model-PC isolated closed-loop lane model comparison; never a device launch.
# One Pinky on map_v2_fleet_real in keep mode, with selectable paint input.
#
#   [BRIDGE=1] [SITE=1] [RECOVERY=true] bash run_sim.sh      # nohup it; it waits on the launch
#
# CORE overlay declares the same site floor and IR/path guards for every model.
WS=${WS:-$HOME/rosy_lane_loop_ws}
PORT=${PORT:-8594}
HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL=${MODEL:-threshold}
case "$MODEL" in
  threshold) PAINT_SOURCE=threshold; MODEL_ARGS=() ;;
  pidnet|unet|v11|v13_drivable) PAINT_SOURCE=learned; MODEL_ARGS=("learned_lane_pointer:=$WS/model_candidates/$MODEL/pointer") ;;
  *) echo "unknown MODEL=$MODEL" >&2; exit 2 ;;
esac
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
# CORE's Python deps (deploy/robot/pinky_pro/requirements-core.txt) in a workspace target dir
# (copied from the D-476 workspace: uv pip install --target pydeps fastapi pydantic uvicorn websockets).
export PYTHONPATH=$WS/pydeps:$PYTHONPATH
export ROSY_LEARNED_SITE=$HOME/rosy-ml/.venv/lib/python3.12/site-packages
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH
done
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-95} GZ_PARTITION=${GZ_PARTITION:-rosy_lane_loop}
RUN=$WS/loop; mkdir -p "$RUN"
SHARE=$(ros2 pkg prefix gz_sim)/share/gz_sim
sed "s/api_port: 8080/api_port: $PORT/" "$SHARE/config/map_v2_fleet_core.yaml" > "$RUN/core_overlay.yaml"
cat >> "$RUN/core_overlay.yaml" <<YAML
line_follow:
  obstacle_mode: path
  ir_guard_enabled: true
  site_floor_map_id: map_v2_fleet
YAML
# Stop every process of an earlier run of this partition: a stopped launch leaves bridges and
# nodes behind (2026-10-07: three parameter_bridges tripled every odom message, same stamp, which
# breaks CORE's PoseTrail). Only processes whose environment carries GZ_PARTITION=$GZ_PARTITION.
for p in $(pgrep -u "$(id -u)"); do
  [ "$p" = "$$" ] && continue
  tr '\000' '\n' 2>/dev/null < /proc/$p/environ | grep -qx "GZ_PARTITION=$GZ_PARTITION" && kill "$p" 2>/dev/null
done
sleep 4
cp "$(ros2 pkg prefix control)/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world" "$RUN/loop_fleet_real.world"
ros2 launch "$HERE/closed_loop.launch.py" core_overlay:="$RUN/core_overlay.yaml" world:="$RUN/loop_fleet_real.world" camera_lane_mode:=keep paint_source:="$PAINT_SOURCE" "${MODEL_ARGS[@]}" "$@" > "$RUN/launch.log" 2>&1 &
LPID=$!
echo "sim up: model=$MODEL CORE http://127.0.0.1:$PORT (launch pid $LPID)"
wait $LPID
