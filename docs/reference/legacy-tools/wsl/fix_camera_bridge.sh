#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
echo "==bridge yaml=="
cat /tmp/rosy_gz_multi_r2doy9ov/bridge_rosy_01.yaml 2>/dev/null | head -20
echo "==start republish=="
nohup ros2 run image_transport republish raw in:=/rosy_01/camera/image_raw compressed out:=/rosy_01/camera/preview/compressed > /tmp/rosy_republish.log 2>&1 &
sleep 4
timeout 8 ros2 topic hz /rosy_01/camera/preview/compressed 2>&1 | tail -2
echo "==core vision status=="
curl -s -H "Authorization: Bearer rosy-dev-operator" http://127.0.0.1:8080/api/v1/vision/front/status
echo
