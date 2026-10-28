#!/usr/bin/env bash
# Install ROS-free dependencies beside the colcon-owned namespace packages.
# TMPDIR controls all wheel/source build residue; the workspace stays untouched.
set -euo pipefail

WORKSPACE="${1:?workspace required}"
INSTALL_ROOT="${2:?install root required}"
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONTRACT_SITE="$INSTALL_ROOT/lib/python$PYTHON_VERSION/site-packages"
CONTRACT_WORK="$(mktemp -d)"
trap 'rm -rf -- "$CONTRACT_WORK"' EXIT
mkdir -p "$CONTRACT_WORK/wheels"
for package in skill motion; do
    mkdir -p "$CONTRACT_WORK/$package"
    cp "$WORKSPACE/contracts/$package/pyproject.toml" "$CONTRACT_WORK/$package/"
    cp -a "$WORKSPACE/contracts/$package/src" "$CONTRACT_WORK/$package/"
done
WHEEL_SOURCES=("$CONTRACT_WORK/skill" "$CONTRACT_WORK/motion")
WHEEL_NAMES=(rosy-contracts-skill==0.1.0 rosy-contracts-motion==0.1.0)
# D-789/D-791: the optional robot media wheel (camera mailbox tap + WHIP worker).
if [[ -f "$WORKSPACE/middleware/media/pyproject.toml" ]]; then
    mkdir -p "$CONTRACT_WORK/media"
    cp "$WORKSPACE/middleware/media/pyproject.toml" "$CONTRACT_WORK/media/"
    cp -a "$WORKSPACE/middleware/media/src" "$CONTRACT_WORK/media/"
    WHEEL_SOURCES+=("$CONTRACT_WORK/media")
    WHEEL_NAMES+=(rosy-media-edge==0.1.0)
fi
if [[ -f "$WORKSPACE/operations/fleet/package.xml" ]]; then
    mkdir -p "$CONTRACT_WORK/execution"
    cp "$WORKSPACE/operations/site_execution/pyproject.toml" "$CONTRACT_WORK/execution/"
    cp -a "$WORKSPACE/operations/site_execution/src" "$CONTRACT_WORK/execution/"
    WHEEL_SOURCES+=("$CONTRACT_WORK/execution")
    WHEEL_NAMES+=(rosy-execution==0.1.2)
fi
python3 -m pip wheel --no-deps --no-build-isolation --no-cache-dir \
    --wheel-dir "$CONTRACT_WORK/wheels" "${WHEEL_SOURCES[@]}"
# core_common is supplied by colcon, not fetched by the offline installer.
python3 -m pip install --no-deps --no-cache-dir --no-index --ignore-installed \
    --find-links "$CONTRACT_WORK/wheels" --target "$CONTRACT_WORK/installed" "${WHEEL_NAMES[@]}"
# pip --target would skip the existing rosy directory. Merge disjoint owners only;
# reject all collisions before writing, preserving stale/reuse refusal.
python3 - "$CONTRACT_WORK/installed" "$CONTRACT_SITE" <<'PY'
from pathlib import Path
import shutil
import sys
source, destination = map(Path, sys.argv[1:])
files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
if any((destination / p.relative_to(source)).exists() for p in files):
    raise SystemExit('FAIL: release dependency files already exist')
for path in files:
    target = destination / path.relative_to(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
PY
PYTHONPATH="$CONTRACT_SITE${PYTHONPATH:+:$PYTHONPATH}" python3 - "$CONTRACT_SITE" <<'PY'
from pathlib import Path
import sys
from rosy.contracts import motion, skill
root = Path(sys.argv[1]).resolve()
modules = [motion, skill]
if (root / 'rosy/execution/site/workflow.py').is_file():
    from rosy.execution.site import goal_evidence, workflow
    modules += [goal_evidence, workflow]
for module in modules:
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise RuntimeError("motion contract dependency resolved outside the release")
assert motion.BaseTwist(0.0, 0.0).linear_mps == 0.0
assert (motion.BaseTwist(0.1, -0.2).linear_mps, motion.BaseTwist(0.1, -0.2).angular_radps) == (0.1, -0.2)
assert motion.MotionHeader("smoke", "device", "representation-only", "IDLE", 0.0, 1.0).attempt is None
assert skill.AttemptIdentity is not None
if (root / 'rosy_media_edge').is_dir():
    assert (root / 'rosy_media_edge/worker.py').is_file() and (root / 'rosy_media_edge/camera_tap.py').is_file()
print("MOTION_CONTRACTS_INSTALLED", root)
PY
