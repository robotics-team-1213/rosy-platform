#!/bin/bash
# Real-profile map_v2_fleet sim in 'keep' mode for the closed-loop lap bench
# and for a tablet (pilot) to watch it (D-364 5). Runs in WSL, foreground:
# keep the calling wsl.exe open or WSL may stop the distro.
#
#   wsl -d Ubuntu -- bash "/mnt/f/.../docs/validation/map-v2-fleet-keep-2026-09-30/run_sim.sh"
#
# CORE listens on 127.0.0.1:8093 (8080 may belong to another sim); Windows
# reaches it as http://127.0.0.1:8093 through WSL localhost forwarding.
# Sim-only CORE overlay (not device defaults): LiDAR obstacle stop 0.10 /
# resume 0.14 m, because at the L-corners the perimeter wall is ~0.2 m ahead.
WS=${WS:-/rosy_realprof_ws}
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
cd $WS; source /opt/ros/jazzy/setup.bash; source install/setup.bash
export ROS_DOMAIN_ID=53 GZ_PARTITION=rosy_realprof
mkdir -p $WS/keep
sed 's/api_port: 8080/api_port: 8093/' src/sim/gz_sim/config/map_v2_fleet_core.yaml > $WS/keep/core_8093.yaml
cat >> $WS/keep/core_8093.yaml <<'YAML'
line_follow:
  obstacle_stop_m: 0.10
  obstacle_resume_m: 0.14
YAML
tr -d '\r' < "$REPO/tools/sim_jpeg_relay.py" > $WS/keep/sim_jpeg_relay.py
pkill -f "ros2 launch gz_sim map_v2_fleet_real.launch.py"
pkill -f "gz sim.*$WS/install/control/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world"
pkill -f "$WS/keep/sim_jpeg_relay"
sleep 2
# lane_corner_turning is already true in map_v2_fleet_real.launch.py.
ros2 launch gz_sim map_v2_fleet_real.launch.py camera_lane_mode:=keep core_overlay:=$WS/keep/core_8093.yaml "$@" > $WS/keep/launch.log 2>&1 &
LPID=$!
for i in $(seq 1 60); do sleep 2; ros2 topic list 2>/dev/null | grep -q camera/front && break; done
# CORE's /api/v1/vision/front/* reads camera/preview/compressed (jpeg).
python3 $WS/keep/sim_jpeg_relay.py --ros-args -r camera/image_raw:=camera/front -p use_sim_time:=true \
  -r __node:=realprof_jpeg_relay > $WS/keep/relay.log 2>&1 &
echo "sim up: CORE http://127.0.0.1:8093 (launch pid $LPID)"
wait $LPID
