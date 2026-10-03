#!/usr/bin/env bash
# Install both ROS-free namespace wheels into the merge-install release tree.
# TMPDIR controls all wheel/source build residue; the workspace stays untouched.
set -euo pipefail

WORKSPACE="${1:?workspace required}"
INSTALL_ROOT="${2:?install root required}"
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONTRACT_SITE="$INSTALL_ROOT/lib/python$PYTHON_VERSION/site-packages"
# pip --target does not merge an existing namespace directory. Refuse reuse
# rather than silently retain stale code or overwrite another namespace owner.
[[ ! -e "$CONTRACT_SITE/rosy" ]] || { echo "FAIL: release contract namespace already exists" >&2; exit 1; }
CONTRACT_WORK="$(mktemp -d)"
trap 'rm -rf -- "$CONTRACT_WORK"' EXIT
mkdir -p "$CONTRACT_WORK/wheels"
for package in skill motion; do
    mkdir -p "$CONTRACT_WORK/$package"
    cp "$WORKSPACE/contracts/$package/pyproject.toml" "$CONTRACT_WORK/$package/"
    cp -a "$WORKSPACE/contracts/$package/src" "$CONTRACT_WORK/$package/"
done
python3 -m pip wheel --no-deps --no-build-isolation --no-cache-dir \
    --wheel-dir "$CONTRACT_WORK/wheels" "$CONTRACT_WORK/skill" "$CONTRACT_WORK/motion"
mkdir -p "$CONTRACT_SITE"
python3 -m pip install --no-cache-dir --no-index --ignore-installed \
    --find-links "$CONTRACT_WORK/wheels" --target "$CONTRACT_SITE" \
    rosy-contracts-skill==0.1.0 rosy-contracts-motion==0.1.0
PYTHONPATH="$CONTRACT_SITE${PYTHONPATH:+:$PYTHONPATH}" python3 - "$CONTRACT_SITE" <<'PY'
from pathlib import Path
import sys
from rosy.contracts import motion, skill
root = Path(sys.argv[1]).resolve()
for module in (motion, skill):
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise RuntimeError("motion contract dependency resolved outside the release")
assert motion.BaseTwist(0.0, 0.0).linear_mps == 0.0
assert (motion.BaseTwist(0.1, -0.2).linear_mps, motion.BaseTwist(0.1, -0.2).angular_radps) == (0.1, -0.2)
assert motion.MotionHeader("smoke", "device", "representation-only", "IDLE", 0.0, 1.0).attempt is None
assert skill.AttemptIdentity is not None
print("MOTION_CONTRACTS_INSTALLED", root)
PY
