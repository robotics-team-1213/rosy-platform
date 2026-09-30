#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
timeout 8 ros2 topic info /rosy_01/camera/preview/compressed -v 2>&1 | grep -E "Node name|Namespaces:|Publisher count|Subscription count|Reliability|Durability" | head -16
