#!/usr/bin/env bash
# D-927 C4: MuJoCo + the shared OMX layer + the cell owner with the C3 ARM_TRANSFER installation + the state writer.
# OUT gets installation.json, installation.bases.json, sim-state.json and sockets/<instance>/control.sock.
# The Fleet that dispatches passes ROSY_FLEET_FENCE_URL/TOKEN (read only at dispatch). CHECK=1 (remote_sim cmd):
#   remote_sim.py --host ai cmd -- "CHECK=1 tools/sim/run_arm_transfer_sim.sh"
set -eo pipefail
source /opt/ros/jazzy/setup.bash
[[ -n ${OMX_CELL_OVERLAY:-} ]] || eval "$("$(dirname "${BASH_SOURCE[0]}")/provision_sim_host.sh")"
source "$OMX_CELL_OVERLAY/setup.bash"
source "${TOPIC_BASED_OVERLAY:-$HOME/rosy-test/overlays/topic_based_ros2_control-aa9f9ef952/install}/setup.bash"
set -u
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true' EXIT
mkdir -p "$OUT/journal" "$OUT/sockets"
python3 "$here/transfer_installation.py" write --out "$OUT/installation.json"
python3 "$here/omx_topic_backend.py" --out "$OUT/layer" >"$OUT/layer.log" 2>&1 &
pids+=($!)
until [[ -s "$OUT/layer/omx_f_topic.urdf" ]]; do sleep 0.5; done
MUJOCO_GL=egl "${SIM_MUJOCO_PYTHON:-$HOME/rosy-test/venvs/sim-mujoco/bin/python}" "$here/omx_mujoco_backend.py" \
  --urdf "$OUT/layer/omx_f_topic.urdf" --shape 240x320 --camera-hz 1 >"$OUT/backend.log" 2>&1 &
pids+=($!)
for _ in $(seq 240); do grep -q OMX_TOPIC_BACKEND_READY "$OUT/layer.log" && break; sleep 0.5; done
grep -q OMX_TOPIC_BACKEND_READY "$OUT/layer.log" || { tail -n 20 "$OUT/layer.log" "$OUT/backend.log"; exit 1; }
instance=$(python3 -c "import json,sys; print(next(iter(json.load(open(sys.argv[1])))))" "$OUT/installation.bases.json")
ROSY_SIM_REPO="$repo" ROSY_FLEET_PEER_UID="${ROSY_FLEET_PEER_UID:-$(id -u)}" ROSY_CELL_OWNER_JOURNAL="$OUT/journal" \
  ROSY_OMX_SOCKET_ROOT="$OUT/sockets" ROSY_ARM_TRANSFER_INSTALLATION="$OUT/installation.json" \
  ROSY_FLEET_FENCE_URL="${ROSY_FLEET_FENCE_URL:-http://127.0.0.1:9/api/fleet/dispatch-control}" \
  ROSY_FLEET_FENCE_TOKEN="${ROSY_FLEET_FENCE_TOKEN:-no-fleet-yet}" \
  python3 "$repo/deploy/robot/omx/run_cell_owner.py" >"$OUT/owner.log" 2>&1 &
pids+=($!)
python3 "$here/transfer_state_writer.py" --assets "$repo/learning/envs/isaac/assets/open_manipulator_description" \
  --bases "$OUT/installation.bases.json" --instance "$instance" --state "$OUT/sim-state.json" \
  --object "$(python3 -c "import json,sys; o=json.load(open(sys.argv[1]))['object']; print(o['body']+'='+o['ref'])" \
    "$OUT/installation.json")" >"$OUT/writer.log" 2>&1 &
pids+=($!)
for _ in $(seq 240); do [[ -S "$OUT/sockets/$instance/control.sock" && -s "$OUT/sim-state.json" ]] && break; sleep 0.5; done
[[ -S "$OUT/sockets/$instance/control.sock" && -s "$OUT/sim-state.json" ]] || {
  tail -n 30 "$OUT/owner.log" "$OUT/writer.log"; exit 1; }
echo ARM_TRANSFER_SIM_READY
if [[ ${CHECK:-} == 1 ]]; then
  python3 "$here/transfer_installation.py" check --out "$OUT/installation.json" --sockets "$OUT/sockets" \
    --state "$OUT/sim-state.json"
  exit
fi
wait -n "${pids[@]}"
