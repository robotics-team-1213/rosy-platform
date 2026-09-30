#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
echo "==raw hz=="
timeout 10 ros2 topic hz /rosy_01/camera/image_raw 2>&1 | tail -2
echo "==raw info=="
timeout 6 ros2 topic info /rosy_01/camera/image_raw 2>&1
echo "==compressed info=="
timeout 6 ros2 topic info /rosy_01/camera/preview/compressed 2>&1
echo "==gz sim camera sensor check=="
gz topic -l 2>/dev/null | grep -E "rosy_01/camera" | head -4
timeout 5 gz topic -e -t 1 /rosy_01/camera/image_raw 2>/dev/null | head -3 || echo "gz echo no data"
