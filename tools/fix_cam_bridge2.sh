#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
pkill -f "rosy_01/camera/image_raw" 2>/dev/null || true
sleep 1
nohup ros2 run ros_gz_bridge parameter_bridge "/rosy_01/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image" \
  > /tmp/rosy_cam_bridge2.log 2>&1 &
sleep 5
echo "==raw hz=="
timeout 10 ros2 topic hz /rosy_01/camera/image_raw --window 20 2>&1 | tail -2
echo "==compressed hz=="
timeout 10 ros2 topic hz /rosy_01/camera/preview/compressed --window 20 2>&1 | tail -2
echo "==core vision=="
curl -s -H "Authorization: Bearer rosy-dev-operator" http://127.0.0.1:8080/api/v1/vision/front/status
echo
