#!/usr/bin/env bash
# D-877: make a lab PC ready for every simulator backend, or confirm it is. Builds only what is missing, under
# ~/rosy-test/overlays/ and the named venv ~/rosy-test/venvs/sim-mujoco, which host cleanup never deletes
# (rosy-ops docs/lab-host-storage.md). Prints export lines for the runners; a second run builds nothing.
# Isaac's SDK venv is installed by hand (learning/envs/isaac) and only reported here.
# Usage: eval "$(tools/sim/provision_sim_host.sh)"
set -eo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
overlay=$("$here/build_omx_overlay.sh" | tail -n 1)
topic=$("$here/build_topic_based_ros2_control.sh" | tail -n 1)
venv="$HOME/rosy-test/venvs/sim-mujoco"
# System site packages give the backend rclpy and the ROS messages; only MuJoCo is added.
[[ -x "$venv/bin/python" ]] || /usr/bin/python3 -m venv --system-site-packages "$venv" >&2
"$venv/bin/python" -c 'import mujoco; assert mujoco.__version__ == "3.3.7"' 2>/dev/null \
  || "$venv/bin/pip" install -q mujoco==3.3.7 >&2
echo "export OMX_CELL_OVERLAY=${overlay#*=} TOPIC_BASED_OVERLAY=${topic#*=} SIM_MUJOCO_PYTHON=$venv/bin/python"
sdk="$HOME/rosy-isaac-ready/sdk-path.txt"
echo "# isaac sdk: $([[ -f $sdk ]] && cat "$sdk" || echo 'not installed (model PC only)')"
