#!/usr/bin/env bash
# D-553 addendum 3: build the ARM64 payload-builder image (build-payload-builder.yml).
# It is only a cache of build prerequisites: Ubuntu 24.04 pinned by digest, the
# ROS snapshot prerequisites (install-ros-build-prereqs.sh, D-482 pins) and the
# apt packages rosdep resolves for this checkout's colcon roots. The payload
# build still runs rosdep install against the same snapshot, so a dependency
# added after the image was built is installed then (slower, same result).
# Usage, from the repository root on an aarch64 Docker host: make-builder-image.sh <image:tag>
set -euo pipefail
IMAGE="${1:?usage: make-builder-image.sh <image:tag>}"
# ubuntu:24.04 multi-arch index, resolved 2026-10-10 (arm64: sha256:08571ca1...).
BASE="docker.io/library/ubuntu@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55"
[[ "$(uname -m)" == "aarch64" ]] || { echo "payload builder images are aarch64 only" >&2; exit 1; }
NAME="rosy-payload-builder-$$"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run --name "$NAME" -v "$PWD:/w:ro" -w /w "$BASE" bash -euo pipefail -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq sudo git ca-certificates python3 python3-yaml patch
  bash deploy/robot/pinky_pro/image/payload-builder/install-ros-build-prereqs.sh
  git config --system --add safe.directory "*"
  set +u; source /opt/ros/jazzy/setup.bash; set -u
  read -r -a roots <<< "$(python3 tools/harness/colcon_roots.py)"
  plan="$(rosdep install --from-paths "${roots[@]}" --ignore-src -r -y --rosdistro jazzy --simulate)"
  mapfile -t packages < <(printf "%s\n" "$plan" | python3 deploy/robot/pinky_pro/image/rosdep_apt_batch.py)
  if ((${#packages[@]})); then apt-get install -y -qq "${packages[@]}"; fi
  apt-get clean
  rm -rf /var/lib/apt/lists/*
'
docker commit --change 'CMD ["bash"]' "$NAME" "$IMAGE" >/dev/null
echo "built $IMAGE from $(git rev-parse HEAD)"
