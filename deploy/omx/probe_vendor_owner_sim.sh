#!/usr/bin/env bash
# Run only inside the locked development image with --network none and a read-only
# checkout mounted at /repo. This probes policy wiring; it never opens hardware.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/omx_ws/install/setup.bash
set -u

if [[ ! -r /repo/src/devices/omx/adapter/test/test_omx_ros_runtime_vendor_sim.py ]]; then
  echo "read-only /repo checkout is required" >&2
  exit 2
fi
if [[ -d /dev/serial/by-id ]] || compgen -G '/dev/video*' >/dev/null; then
  echo "simulation probe refuses serial or video device grants" >&2
  exit 2
fi

export PYTHONPATH="/repo/src/devices/omx/adapter:${PYTHONPATH:-}"
export PYTHONDONTWRITEBYTECODE=1
export OMX_VENDOR_SIM_ACTION=/arm_controller/follow_joint_trajectory
export ROS_DOMAIN_ID="${OMX_PROBE_DOMAIN_ID:-75}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export GZ_SIM_PHYSICS_ENGINE_PATH=/opt/ros/jazzy/opt/gz_physics_vendor/lib

ros2 launch open_manipulator_bringup omx_f_follower_ai_gazebo.launch.py \
  >/tmp/rosy-owner-launch.log 2>&1 &
launch_pid=$!
cleanup() {
  kill "$launch_pid" 2>/dev/null || true
  wait "$launch_pid" 2>/dev/null || true
}
trap cleanup EXIT

sleep 10
if ! python3 -m pytest \
  /repo/src/devices/omx/adapter/test/test_omx_ros_runtime_vendor_sim.py \
  -q -p no:cacheprovider --basetemp /tmp/rosy-owner-pytest; then
  tail -n 60 /tmp/rosy-owner-launch.log >&2
  exit 1
fi
