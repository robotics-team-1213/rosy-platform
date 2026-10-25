#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
echo "==gz camera topics=="
timeout 8 gz topic -l 2>/dev/null | grep -iE "camera|image" | head -8
echo "==image_bridge process=="
ps aux | grep -E "image_bridge|parameter_bridge" | grep -v grep | head -4 || echo "none running"
echo "==launch bridge args=="
grep -n -A6 "image_bridge" /rosy/integrations/simulation/gazebo/launch/gz_multi.launch.py | head -30
