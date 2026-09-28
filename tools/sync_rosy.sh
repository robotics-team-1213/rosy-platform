#!/usr/bin/env bash
# 웍트리 최신 pilot 관련 소스를 /rosy(네이티브)로 동기화하고 증분 빌드한다.
set -e
SRC="/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/pilot-teleop"
DST="$HOME/rosy"
[ -d "$DST" ] || { echo "migrate first"; exit 1; }
for rel in src/hmi src/runtime/api_web; do
  rm -rf "$DST/$rel"
  tar -C "$SRC" -cf - "$rel" | tar -C "$DST" -xf -
done
cd "$DST"
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
colcon build --symlink-install --packages-select web dashboard pilot core_api_web 2>&1 | tail -n 6
echo "SYNC_BUILD_DONE"
