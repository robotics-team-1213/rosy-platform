# Sourced by the session wrappers. OMX and PYTHONPATH come from TOOLS_ROOT (the omx-devices release the cell task
# worker runs from), never from the hand-switched ~/rosy-test/omx-tools-current link: the worker and the arm scripts
# must run one release (2026-11-21). Without TOOLS_ROOT the release is the one holding this file.
: "${TOOLS_ROOT:=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
export TOOLS_ROOT
export OMX=$TOOLS_ROOT/deploy/robot/omx
# shortcut: the extra site-packages is the cell's hand-made venv that tools-env-current.sh carried; drop it once ~/rosy-omx/current-env has those packages
ROSY_OMX_EXTRA_SITE=${ROSY_OMX_EXTRA_SITE-$HOME/rosy-test/venvs/9a8fedb7a16a451a/lib/python3.12/site-packages}
export PYTHONPATH=$TOOLS_ROOT/contracts/foundation:$TOOLS_ROOT/operations/overhead:$TOOLS_ROOT/middleware/devices/omx/adapter:$OMX${ROSY_OMX_EXTRA_SITE:+:$ROSY_OMX_EXTRA_SITE}${PYTHONPATH:+:$PYTHONPATH}
export ROSY_OMX_TCP_X_M=0.0740  # v2.1 jaws on arm_a, arm_b, arm_s (arm_s confirmed by wrist photo 2026-11-15)
export ROSY_LOAD_MODEL=$HOME/rosy-test/omx-record-prep-20261019/load-model-20261116.json
