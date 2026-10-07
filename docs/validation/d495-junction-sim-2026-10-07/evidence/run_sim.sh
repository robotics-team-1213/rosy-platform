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
WS=${WS:-$HOME/rosy_d495_ws}
PORT=${PORT:-8097}   # 8095 is the D-476 runs' port on this host
BRIDGE=${BRIDGE:-1}
SITE=${SITE:-1}
RECOVERY=${RECOVERY:-true}   # line_follow.recovery_local_enabled (rosy_default: true)
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
# CORE's Python deps (deploy/robot/pinky_pro/requirements-core.txt) in a workspace target dir
# (copied from the D-476 workspace: uv pip install --target pydeps fastapi pydantic uvicorn websockets).
export PYTHONPATH=$WS/pydeps:$PYTHONPATH
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH
done
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-77} GZ_PARTITION=${GZ_PARTITION:-rosy_d495}
RUN=$WS/d495; mkdir -p "$RUN"
SHARE=$(ros2 pkg prefix gz_sim)/share/gz_sim
if [ "$BRIDGE" = "1" ]; then B=true; else B=false; fi
if [ "$SITE" = "1" ]; then S=true; else S=false; fi
sed "s/api_port: 8080/api_port: $PORT/" "$SHARE/config/map_v2_fleet_core.yaml" > "$RUN/core_overlay.yaml"
cat >> "$RUN/core_overlay.yaml" <<YAML
line_follow:
  obstacle_mode: path
  recovery_local_enabled: $RECOVERY
  ir_guard_enabled: true
  junction_turn_site_accepted: $S
  bridge_enabled: $B
  bridge_site_no_dropoffs: true
YAML
pkill -f "d495_sim_aux.py"
pkill -f "ros2 launch .*d495_real.launch.py"
pkill -f "gz sim.*d495_fleet_real.world"   # never the peer D-476 run's map_v2_fleet_real.world
sleep 2
cp "$(ros2 pkg prefix control)/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world" "$RUN/d495_fleet_real.world"
ros2 launch "$HERE/d495_real.launch.py" core_overlay:="$RUN/core_overlay.yaml" world:="$RUN/d495_fleet_real.world" "$@" > "$RUN/launch.log" 2>&1 &
LPID=$!
echo "sim up: CORE http://127.0.0.1:$PORT bridge=$B site=$S recovery=$RECOVERY (launch pid $LPID)"
wait $LPID
