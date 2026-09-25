#!/bin/bash
# run_fleet_sim.sh
# One-click startup script for multi-robot simulation + sensor control + fleet orchestration

set -e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ROBOTS=${1:-2}
echo "Starting $ROBOTS-robot fleet simulation..."

# 1. Source ROS2 workspace
source /opt/ros/jazzy/setup.bash
source install/setup.bash

# D-117 — 시스템 전체는 CycloneDDS 만 쓴다. 비대화형 셸은 env.sh 를 거치지
# 않으므로 여기서 명시한다. 빠뜨리면 ros_gz_bridge 만 FastDDS 로 떠서
# clock/scan/odom 이 ROS 로 전혀 흐르지 않는다(센서 브리지 FAIL 의 원인).
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# 재기동 사이클마다 SIGKILL 된 프로세스의 DDS 참가자 잔재가 도메인 0 인덱스를
# 고갈시킨다("Failed to find a free participant index"). 실행마다 새 도메인으로
# 격리한다 — fleet 콘솔은 HTTP 여서 영향이 없고, 시뮬 내부는 이 도메인을 공유한다.
export ROS_DOMAIN_ID=$(( (RANDOM % 100) + 20 ))

# Nav2 의 정적 점유 맵(map_server) — mode:=nav 는 map:= 인자를 요구한다.
MAP_YAML="$PWD/src/runtime/control/map/map_260905_update_v2/maps/map_260905.yaml"

# 2. Cleanup previous processes
killall -9 ruby gz python3 parameter_bridge create 2>/dev/null || true

# 3. Start gz_multi.launch.py in the background
echo "[1/3] Starting Gazebo Multi-Robot Environment (core+nav2)..."
ros2 launch src/sim/gz_sim/launch/gz_multi.launch.py robots:=$ROBOTS world_name:=/tmp/map_260905.world map:="$MAP_YAML" mode:=nav core:=true headless:=true spawn_x:=-0.5 spawn_spacing:=1.0 > /tmp/rosy_gz.log 2>&1 &
GZ_PID=$!

echo "Waiting for robots.yaml to be generated..."
ROBOTS_YAML=""
SIM_START=$(date +%s)
for i in {1..240}; do
    # 이번 실행이 시작된 뒤에 생성된 yaml 만 받는다 — 죽은 이전 세대의 stale
    # yaml 을 집으면 죽은 포트의 매니페스트로 콘솔이 떠서 영구 ConnectError 다.
    YAML_PATH=$(find /tmp -maxdepth 2 -path '*rosy_gz_multi*/robots.yaml' \
        -newermt "@$SIM_START" 2>/dev/null | head -n 1)
    if [ -n "$YAML_PATH" ] && [ -f "$YAML_PATH" ]; then
        ROBOTS_YAML=$YAML_PATH
        break
    fi
    sleep 1
done

if [ -z "$ROBOTS_YAML" ]; then
    echo "Error: Failed to find robots.yaml. Simulation might have crashed."
    cat /tmp/rosy_gz.log
    kill $GZ_PID 2>/dev/null || true
    exit 1
fi
echo "Found Fleet manifest: $ROBOTS_YAML"
sleep 5 # Wait a bit longer for Gazebo to fully settle

# 4. Start control/sensing nodes for each robot in the background
echo "[2/3] Starting Control/Sensing stack for each robot..."
for (( i=1; i<=$ROBOTS; i++ )); do
    NS=$(printf "rosy_%02d" $i)
    WEB_PORT=$(( 28151 + i * 10 ))
    BACKEND_PORT=$(( 28152 + i * 10 ))
    
    echo "  -> $NS (Web UI: http://localhost:$WEB_PORT)"
    
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
    export ROSY_NAMESPACE=$NS
    
    ros2 launch control robot.launch.py profile:=sensing localization_required:=false start_camera:=false web_port:=$WEB_PORT web_backend_port:=$BACKEND_PORT > /tmp/rosy_control_$NS.log 2>&1 &
done

# 5. Start Fleet Server
echo "[3/3] Starting Fleet Console..."
export PYTHONPATH="$PYTHONPATH:$(pwd)/src/site/fleet:$(pwd)/src/contracts/foundation:$(pwd)/src/runtime/features"

echo ""
echo "========================================================="
echo "✅ All Systems Running!"
echo ""
echo "📍 Fleet Console:  http://localhost:8090/console"
for (( i=1; i<=$ROBOTS; i++ )); do
    NS=$(printf "rosy_%02d" $i)
    WEB_PORT=$(( 28151 + i * 10 ))
    echo "📍 $NS Web:      http://localhost:$WEB_PORT"
done
echo "========================================================="
echo "Press Ctrl+C to stop all processes."

python3 src/site/fleet/fleet/cli.py console --robots "$ROBOTS_YAML" \
    --ui-tokens "$PWD/src/runtime/api_web/core_api_web/web/tokens.css"

# Cleanup on exit
kill $(jobs -p) 2>/dev/null || true
echo "Stopped."
