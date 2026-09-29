#!/usr/bin/env bash
# 카메라 전체 스택: GZ→ROS 브리지 + JPEG 릴레이. /rosy 기준.
source /opt/ros/jazzy/setup.bash
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

echo "== 기존 카메라 프로세스 정리 =="
pkill -f "rosy_01/camera/image_raw@sensor_msgs" 2>/dev/null
pkill -f "sim_jpeg_relay" 2>/dev/null
sleep 1

echo "== 1. GZ→ROS 단방향 브리지 (image_raw) =="
nohup ros2 run ros_gz_bridge parameter_bridge \
  "/rosy_01/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image" \
  > /tmp/rosy_cam_raw.log 2>&1 &
RAW_PID=$!
sleep 3
echo "  raw bridge PID: $RAW_PID"

echo "== 2. JPEG 릴레이 (image_raw → preview/compressed) =="
nohup python3 /rosy/tools/sim_jpeg_relay.py --ros-args -r __ns:=/rosy_01 \
  > /tmp/rosy_relay.log 2>&1 &
RELAY_PID=$!
sleep 5
echo "  relay PID: $RELAY_PID"

echo "== 3. 확인 =="
echo "-- raw hz (5s) --"
timeout 5 ros2 topic hz /rosy_01/camera/image_raw --window 10 2>&1 | tail -2
echo "-- relay log --"
tail -3 /tmp/rosy_relay.log 2>/dev/null
echo "-- CORE vision --"
curl -s -H "Authorization: Bearer rosy-dev-operator" http://127.0.0.1:8080/api/v1/vision/front/status
echo
echo "== DONE =="
