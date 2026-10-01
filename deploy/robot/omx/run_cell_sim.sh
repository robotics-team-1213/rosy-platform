#!/usr/bin/env bash
# Rosy Cell C3: locked OMX-F Gazebo follower in the omx_cell_workcell world, with NO command
# owner. Run deploy/robot/omx/probe_cell_transfer.py with docker exec in the same container;
# that probe is the one owner process (D-403 §8). Do not start pilot_sim_server beside it.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/omx_ws/install/setup.bash
set -u
# Path without ".sdf" (the vendor launch appends it). Override only for a recorded variant.
world="${OMX_CELL_WORLD:-/repo/src/sim/gz_sim/worlds/omx_cell_workcell}"
test -r "$world.sdf"
export ROS_DOMAIN_ID="${OMX_CELL_DOMAIN_ID:-77}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export GZ_SIM_PHYSICS_ENGINE_PATH=/opt/ros/jazzy/opt/gz_physics_vendor/lib
log_dir="${OMX_CELL_LOG_DIR:-/tmp}"
ros2 launch open_manipulator_bringup omx_f_follower_ai_gazebo.launch.py \
  world:="$world" >"$log_dir/rosy-cell-gazebo.log" 2>&1 &
launch_pid=$!
trap 'kill "$launch_pid" 2>/dev/null || true; wait "$launch_pid" 2>/dev/null || true' EXIT
wait "$launch_pid"
