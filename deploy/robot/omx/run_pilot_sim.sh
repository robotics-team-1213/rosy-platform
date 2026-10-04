#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/omx_ws/install/setup.bash
set -u
test -r /repo/middleware/apps/device/omx/adapter/omx_adapter/pilot_sim_server.py
export PYTHONPATH="/repo/contracts/foundation:/repo/middleware/apps/device/omx/adapter:${PYTHONPATH:-}"
export ROS_DOMAIN_ID="${OMX_PILOT_DOMAIN_ID:-75}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export GZ_SIM_PHYSICS_ENGINE_PATH=/opt/ros/jazzy/opt/gz_physics_vendor/lib
ros2 launch open_manipulator_bringup omx_f_follower_ai_gazebo.launch.py \
  world:=/repo/integrations/simulation/gazebo/worlds/omx_pilot_workcell >/tmp/rosy-pilot-gazebo.log 2>&1 &
launch_pid=$!
ros2 run ros_gz_bridge parameter_bridge \
  '/workcell_camera/image@sensor_msgs/msg/Image[gz.msgs.Image' \
  '/workcell_camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo' >/tmp/rosy-pilot-camera.log 2>&1 &
camera_pid=$!
trap 'kill "$launch_pid" "$camera_pid" 2>/dev/null || true; wait "$launch_pid" "$camera_pid" 2>/dev/null || true' EXIT
python3 -m omx_adapter.pilot_sim_server
