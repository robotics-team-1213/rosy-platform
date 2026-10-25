#!/usr/bin/env bash
# D-866 P2: build PickNikRobotics topic_based_ros2_control at a pinned commit into a user overlay, so any
# simulator that publishes joint states and reads joint commands on topics gets the official OMX
# joint_trajectory_controller (no sudo; Jazzy has no binary package on the lab PCs).
# Usage: tools/sim/build_topic_based_ros2_control.sh [prefix]   (default ~/rosy-test/overlays/topic_based_ros2_control-<commit>)
set -eo pipefail
commit=aa9f9ef9525a60f8becea322537dd1d6d1bf9123
prefix="${1:-$HOME/rosy-test/overlays/topic_based_ros2_control-${commit:0:10}}"
if [[ -f "$prefix/install/setup.bash" ]]; then echo "TOPIC_BASED_ROS2_CONTROL=$prefix/install"; exit 0; fi
source /opt/ros/jazzy/setup.bash
set -u  # After the ROS setup, which reads unset variables.
mkdir -p "$prefix/src"
git -C "$prefix/src" clone --quiet https://github.com/PickNikRobotics/topic_based_ros2_control.git
git -C "$prefix/src/topic_based_ros2_control" checkout --quiet "$commit"
(cd "$prefix" && colcon build --packages-select topic_based_ros2_control --cmake-args -DBUILD_TESTING=OFF -DPython3_EXECUTABLE=/usr/bin/python3 -DPYTHON_EXECUTABLE=/usr/bin/python3 >build.log 2>&1) \
  || { tail -30 "$prefix/build.log"; exit 1; }
echo "TOPIC_BASED_ROS2_CONTROL=$prefix/install"
