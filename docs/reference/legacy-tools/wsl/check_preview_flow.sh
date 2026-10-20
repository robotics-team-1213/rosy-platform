#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
echo "==hz preview (8s)=="
timeout 8 ros2 topic hz /rosy_01/camera/preview/compressed 2>&1 | tail -3
echo "==subscribers of preview=="
timeout 6 ros2 topic info /rosy_01/camera/preview/compressed 2>&1
echo "==api vision status=="
curl -s -H "Authorization: Bearer rosy-dev-operator" http://127.0.0.1:8080/api/v1/vision/front/status
echo
