#!/usr/bin/env bash
# 카메라 스택 일괄 기동: gz raw 브리지(GZ→ROS) + jpeg 릴레이. CORE/가제보는 건드리지 않는다.
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
pkill -f "image_transport republish" 2>/dev/null || true
pkill -f "ros_gz_bridge parameter_bridge /rosy_01/camera" 2>/dev/null || true
pkill -f "sim_jpeg_relay" 2>/dev/null || true
sleep 1
nohup ros2 run ros_gz_bridge parameter_bridge "/rosy_01/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image" \
  > /tmp/rosy_cam_raw.log 2>&1 &
nohup python3 /rosy/tools/sim_jpeg_relay.py --ros-args -r __ns:=/rosy_01 \
  > /tmp/rosy_relay.log 2>&1 &
sleep 8
echo "==relay log=="
tail -3 /tmp/rosy_relay.log 2>/dev/null
echo "==raw hz=="
timeout 10 ros2 topic hz /rosy_01/camera/image_raw --window 20 2>&1 | tail -2
echo "==compressed hz=="
timeout 10 ros2 topic hz /rosy_01/camera/preview/compressed --window 20 2>&1 | tail -2
echo "==core vision=="
curl -s -H "Authorization: Bearer rosy-dev-operator" http://127.0.0.1:8080/api/v1/vision/front/status
echo
