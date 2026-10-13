#!/bin/bash
# D-495/D-498 junction SIM acceptance (model PC only; never on the Windows laptop).
# One Pinky on map_v2_fleet_real in keep mode, launched through d495_real.launch.py.
#
#   [BRIDGE=1] [SITE=1] [RECOVERY=true] bash run_sim.sh      # nohup it; it waits on the launch
#
# CORE overlay (ROSY_CONFIG, the documented overlay path) = gz_sim config/map_v2_fleet_core.yaml
# with api_port $PORT plus the site layer below. Payload line_follow.yaml is untouched (H1).
# Body geometry and obstacle_mode path come from the pinky_pro robot package core.yaml; the
# overlay repeats obstacle_mode path only to make it explicit. No control.sensor_adapter (off,
# as on the device): the D-498 'site' basis is the only turn basis here.
WS=${WS:-$HOME/rosy_lfstop_ws}
PORT=${PORT:-8109}
BRIDGE=${BRIDGE:-1}
SITE=${SITE:-1}
RECOVERY=${RECOVERY:-false}
HERE="$WS/route_a_sim"
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source $HOME/rosy_bend_window_ws/install/setup.bash; source install/setup.bash
# CORE's Python deps (deploy/robot/pinky_pro/requirements-core.txt) in a workspace target dir
# (copied from the D-476 workspace: uv pip install --target pydeps fastapi pydantic uvicorn websockets).
export PYTHONPATH=$HOME/rosy_bend_window_ws/pydeps:$PYTHONPATH
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH
done
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-99} GZ_PARTITION=${GZ_PARTITION:-rosy_lane_route99}
RUN=$WS/route_a_sim/run; mkdir -p "$RUN"
SHARE=$(ros2 pkg prefix gz_sim)/share/gz_sim
if [ "$BRIDGE" = "1" ]; then B=true; else B=false; fi
if [ "$SITE" = "1" ]; then S=true; else S=false; fi
sed "s/api_port: 8080/api_port: $PORT/" "$SHARE/config/map_v2_fleet_core.yaml" > "$RUN/core_overlay.yaml"
cat >> "$RUN/core_overlay.yaml" <<YAML
line_follow:
  obstacle_mode: path
  recovery_local_enabled: $RECOVERY
  ir_guard_enabled: true
  site_floor_map_id: map_v2_fleet
  bridge_enabled: $B
YAML
cp "$(ros2 pkg prefix control)/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world" "$RUN/lfw_fleet_real.world"
ros2 launch "$HERE/d495_real.launch.py" core_overlay:="$RUN/core_overlay.yaml" world:="$RUN/lfw_fleet_real.world" "$@" > "$RUN/launch.log" 2>&1 &
LPID=$!
echo "sim up: CORE http://127.0.0.1:$PORT bridge=$B site=$S recovery=$RECOVERY (launch pid $LPID)"
wait $LPID
