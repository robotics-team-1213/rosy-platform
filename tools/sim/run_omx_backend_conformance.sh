#!/usr/bin/env bash
# D-866 P2: start the shared OMX layer plus one simulator adapter, then judge it with omx_backend_conformance.py.
# remote_sim only (it sets OUT and an isolated ROS domain):
#   remote_sim.py ... cmd -- "OMX_CELL_OVERLAY=... tools/sim/run_omx_backend_conformance.sh mujoco 240x320 5"
set -eo pipefail
backend="$1" shape="$2" camera_hz="$3"
source /opt/ros/jazzy/setup.bash
source "${OMX_CELL_OVERLAY:?}/setup.bash"
source "${TOPIC_BASED_OVERLAY:-$HOME/rosy-test/overlays/topic_based_ros2_control-aa9f9ef952/install}/setup.bash"
set -u
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true' EXIT
python3 "$here/omx_topic_backend.py" --out "$OUT/layer" >"$OUT/layer.log" 2>&1 &
pids+=($!)
until [[ -s "$OUT/layer/omx_f_topic.urdf" ]]; do sleep 0.5; done
case "$backend" in
  mujoco)
    MUJOCO_GL=egl "${SIM_MUJOCO_PYTHON:-$HOME/rosy-test/venvs/sim-mujoco/bin/python}" "$here/omx_mujoco_backend.py" \
      --urdf "$OUT/layer/omx_f_topic.urdf" --shape "$shape" --camera-hz "$camera_hz" >"$OUT/backend.log" 2>&1 &
    pids+=($!) ;;
  *) echo "unknown backend $backend" >&2; exit 2 ;;
esac
for _ in $(seq 240); do grep -q OMX_TOPIC_BACKEND_READY "$OUT/layer.log" && break; sleep 0.5; done
grep -q OMX_TOPIC_BACKEND_READY "$OUT/layer.log" || { tail -20 "$OUT/layer.log" "$OUT/backend.log"; exit 1; }
python3 "$here/omx_backend_conformance.py" --shape "$shape" --camera-hz "$(python3 -c "print($camera_hz*.9)")" \
  --out "$OUT/conformance.json"
