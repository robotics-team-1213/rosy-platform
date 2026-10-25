#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
echo "==format field=="
timeout 8 ros2 topic echo /rosy_01/camera/preview/compressed --field format --once 2>&1 | head -2
echo "==cv2=="
python3 -c "import cv_bridge; print('cv_bridge ok')" 2>&1 | head -1
python3 -c "import PIL; print('PIL ok')" 2>&1 | head -1
