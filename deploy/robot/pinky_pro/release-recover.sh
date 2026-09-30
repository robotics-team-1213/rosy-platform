#!/usr/bin/env bash
# Finish an interrupted update before the runtime is allowed to start.
#
# Exit status is the gate: 0 lets rosy-runtime.service proceed, non-zero holds
# the device. That is why this script has no `|| true` anywhere and why the
# unit has no Restart= — either would convert a hold into a boot.
set -euo pipefail

RELEASE_TOOLS="${ROSY_RELEASE_TOOLS:-/opt/rosy/deploy/release}"
PYTHON="${ROSY_PYTHON:-python3}"

if [[ ! -d "$RELEASE_TOOLS" ]]; then
    echo "release tools not found at $RELEASE_TOOLS" >&2
    exit 1
fi

# ROSY_LAYOUT_ROOT exists so this gate can be exercised against a temporary
# tree. Without it the only way to check that a hold actually blocks a boot is
# to read the source and believe it, and a gate nobody can run is a gate
# nobody has tested.
exec "$PYTHON" - "$RELEASE_TOOLS" "${ROSY_LAYOUT_ROOT:-}" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from layout import Layout
from updater import Updater

layout_root = sys.argv[2] if len(sys.argv) > 2 else ""
layout = Layout.rooted(Path(layout_root)) if layout_root else Layout.default()


def _noop(*_args, **_kwargs):
    return None


def _systemctl(action, unit="rosy-runtime.service"):
    import subprocess

    subprocess.run(["systemctl", action, unit], check=False)


updater = Updater(
    layout,
    stop_runtime=lambda: _systemctl("stop"),
    start_runtime=lambda _mode: _systemctl("start"),
    # The gate decides whether boot proceeds; it does not health-check a
    # runtime it has not started. A candidate's health was already judged by
    # the activation that was interrupted.
    health_check=lambda: True,
    disable_runtime=lambda: _systemctl("disable"),
)

outcome = updater.recover()
print(f"{outcome.state.value}: {outcome.detail}")

if outcome.blocks_runtime:
    # RECOVERY HOLD. A fresh device reports NOT_INSTALLED and does not block,
    # which is why this keys on blocks_runtime rather than on ok.
    sys.exit(1)
PY
