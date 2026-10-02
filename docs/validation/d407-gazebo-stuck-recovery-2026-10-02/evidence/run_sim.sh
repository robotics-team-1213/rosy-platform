#!/bin/bash
# D-407 lane stuck recovery in Gazebo: one Pinky on the real-profile map_v2_fleet
# track in 'keep' mode (lane ends at wall corners, lane is lost at the roundabout).
# Runs in WSL in the foreground: keep the calling wsl.exe open or WSL may stop the distro.
#
#   wsl -d Ubuntu -- bash ".../docs/validation/d407-gazebo-stuck-recovery-2026-10-02/evidence/run_sim.sh" [spawn_x:=.. ...]
#
# Sim-only CORE overlay (device defaults untouched): api_port 8095 and
# line_follow.recovery_local_enabled true. Obstacle stop/resume stay at the device
# defaults (0.20/0.28 m) so the perimeter wall at the L corners stops the robot.
# Body geometry (body_lidar_x_m / body_rear_x_m / rotation radius) comes from the
# pinky_pro robot package core.yaml (URDF nominal), exactly as on the device.
#
# REAR_BLIND=1 adds a rear self-mask window so the rear blind band matches the device.
# FAKE_HUB=1 also points the FleetAgent at tools/sim/d407_stuck_scenarios.py's fake hub
# (ws://127.0.0.1:8096/ws/robots) so console_linked is true and a stuck stays ASKING for
# recovery_ask_s; start the hub first (d407_stuck_scenarios.py hub). As of 7e577452 this
# reproduces a CORE start crash instead (FleetAgent.start outside an event loop, result.md).
WS=${WS:-/rosy_d407_ws}
PORT=${PORT:-8095}
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
cd "$WS" || exit 1
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-57} GZ_PARTITION=${GZ_PARTITION:-rosy_d407}
RUN=$WS/d407; mkdir -p "$RUN"
sed "s/api_port: 8080/api_port: $PORT/" src/sim/gz_sim/config/map_v2_fleet_core.yaml > "$RUN/core_overlay.yaml"
cat >> "$RUN/core_overlay.yaml" <<'YAML'
line_follow:
  recovery_local_enabled: true
YAML
if [ "${REAR_BLIND:-0}" = "1" ]; then
  # Trail-rule bench: the sim LiDAR's range_min is 0.05 m (< 0.059 m LiDAR-to-body-rear),
  # so its rear blind band is 0. A rear self-mask window reaching 0.15 m (the C1's
  # range_min) hides 0.091 m behind the body rear, as on the device, so the
  # "space it just drove through" rule (recovery_trail_s) has to admit every back-off.
  cat >> "$RUN/core_overlay.yaml" <<'YAML'
  lidar_self_mask:
    - {from_deg: 165.0, to_deg: 180.0, max_range_m: 0.15}
    - {from_deg: -180.0, to_deg: -165.0, max_range_m: 0.15}
YAML
fi
if [ "${FAKE_HUB:-0}" = "1" ]; then
  cat >> "$RUN/core_overlay.yaml" <<'YAML'
fleet:
  hub_url: http://127.0.0.1:8096
  pairing_token: d407-sim-pairing
YAML
fi
tr -d '\r' < "$REPO/tools/sim_jpeg_relay.py" > "$RUN/sim_jpeg_relay.py"
pkill -f "ros2 launch gz_sim map_v2_fleet_real.launch.py"
pkill -f "gz sim.*$WS/install/control/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world"
pkill -f "$RUN/sim_jpeg_relay"
sleep 2
ros2 launch gz_sim map_v2_fleet_real.launch.py camera_lane_mode:=keep \
  core_overlay:="$RUN/core_overlay.yaml" "$@" > "$RUN/launch.log" 2>&1 &
LPID=$!
for i in $(seq 1 60); do sleep 2; ros2 topic list 2>/dev/null | grep -q camera/front && break; done
# CORE's preview sequence (stuck event preview_seq) reads camera/preview/compressed.
python3 "$RUN/sim_jpeg_relay.py" --ros-args -r camera/image_raw:=camera/front -p use_sim_time:=true \
  -r __node:=d407_jpeg_relay > "$RUN/relay.log" 2>&1 &
echo "sim up: CORE http://127.0.0.1:$PORT (launch pid $LPID, overlay $RUN/core_overlay.yaml)"
wait $LPID
