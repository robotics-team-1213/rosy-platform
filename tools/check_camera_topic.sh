#!/usr/bin/env bash
# 시뮬 카메라 토픽 확인(시뮬 실행 중)
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
timeout 8 ros2 topic list 2>/dev/null | grep -iE "image|camera" | head -10
echo "===hz==="
timeout 6 ros2 topic hz /rosy_01/front_camera/image 2>/dev/null | head -2
