#!/usr/bin/env bash
# Build the pinned CPU learner venv the Learning center and the pinned-learner tests use, or confirm it is there.
# Path: ~/.local/share/rosy-learning-center/venv-cpu (host_caps.py "learner_venv" is its presence; a host without it
# is never given a HOST_CAPABILITIES = ("learner_venv",) test). Pins: deploy/robot/omx/requirements-lerobot-export.txt,
# or a full `pip freeze` of the model PC's venv-cpu (minus the local core_common build) as the first argument.
# CPU torch comes from the PyTorch CPU index; unsafe-best-match lets uv take the +cpu wheels from it while the rest
# resolves on PyPI. Needs uv and Python 3.12 (~/.local/bin/python3.12 or /usr/bin/python3). ~1.9 GB. Run it on the host.
# Usage: tools/remote/provision_learner_venv.sh [requirements-file]
set -eo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
req="${1:-$here/../../deploy/robot/omx/requirements-lerobot-export.txt}"
venv="$HOME/.local/share/rosy-learning-center/venv-cpu"
check='import lerobot, torch, sys; sys.exit(not (torch.__version__ == "2.10.0+cpu" and sys.version_info[:2] == (3, 12)))'
if [[ -x "$venv/bin/python" ]] && "$venv/bin/python" -I -B -c "$check" 2>/dev/null; then
  echo "learner venv ready: $venv"; exit 0
fi
command -v uv >/dev/null || { echo "uv is missing (https://docs.astral.sh/uv/)" >&2; exit 1; }
py="$HOME/.local/bin/python3.12"; [[ -x "$py" ]] || py=/usr/bin/python3
"$py" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' || { echo "$py is not Python 3.12" >&2; exit 1; }
uv venv --python "$py" "$venv"
uv pip install --python "$venv/bin/python" --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match -r "$req"
"$venv/bin/python" -I -B -c "$check" && echo "learner venv built: $venv"
