#!/usr/bin/env bash
# D-877: build the ROBOTIS open_manipulator description + bringup overlay that every simulator backend sources
# (OMX_CELL_OVERLAY), from stack.lock.yaml's revision and the three SIM patches in the order the 2026-10-17
# native preparation applied them. The directory name carries the revision and the patch digest, so a patch
# change builds a new overlay beside the old one instead of mutating it. No sudo.
# Usage: tools/sim/build_omx_overlay.sh [prefix]   (default ~/rosy-test/overlays/omx-vendor-<rev10>-<patch10>)
set -eo pipefail
omx="$(cd "$(dirname "$0")/../../deploy/robot/omx" && pwd)"
revision=$(tr -d "" < "$omx/stack.lock.yaml" | sed -n 's/^  revision: \([0-9a-f]\{40\}\)$/\1/p')
[[ ${#revision} == 40 ]] || { echo "no vendor revision in $omx/stack.lock.yaml" >&2; exit 1; }
patches=(omx-f-gazebo-headless omx-ai-sim-gates omx-ai-sim-action-only)
digest=$(cd "$omx/patches" && cat "${patches[@]/%/.patch}" | sha256sum | cut -c1-10)
prefix="${1:-$HOME/rosy-test/overlays/omx-vendor-${revision:0:10}-$digest}"
# colcon writes absolute paths into install/, so the tree is built in place and only the stamp, written last,
# says it is complete; a cut-off build is rebuilt from scratch.
if [[ -f "$prefix/complete" ]]; then echo "OMX_CELL_OVERLAY=$prefix/install"; exit 0; fi
source /opt/ros/jazzy/setup.bash
set -u  # After the ROS setup, which reads unset variables.
rm -rf "$prefix" && mkdir -p "$prefix/src"
src="$prefix/src/open_manipulator"
git init -q "$src"
git -C "$src" fetch -q --depth=1 https://github.com/ROBOTIS-GIT/open_manipulator.git "$revision"
git -C "$src" checkout -q --detach FETCH_HEAD
for patch in "${patches[@]}"; do git -C "$src" apply "$omx/patches/$patch.patch"; done
(cd "$prefix" && colcon build --base-paths src/open_manipulator --merge-install \
   --packages-select open_manipulator_description open_manipulator_bringup \
   --cmake-args -DBUILD_TESTING=OFF -DPython3_EXECUTABLE=/usr/bin/python3 -DPYTHON_EXECUTABLE=/usr/bin/python3 \
   >build.log 2>&1) || { tail -30 "$prefix/build.log" >&2; exit 1; }
echo "$revision ${patches[*]} $digest" > "$prefix/complete"
echo "OMX_CELL_OVERLAY=$prefix/install"
