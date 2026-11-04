"""Where the hardware launch finds the Device profile on a native robot.

Compose bind-mounts ``config/profile.${ROSY_RUNTIME_MODE}.yaml`` over
``/etc/rosy/profile.yaml``; the native payload had no equivalent, so
``hardware.launch.py`` aborted on a fresh device ("cannot read Device
profile", 2026-11-03 solution doc) until someone installed the file by
hand. The payload now ships the mode overlays under
``/opt/rosy/current/deploy/robot/config/`` and this helper picks one.
"""

from __future__ import annotations

import os
from pathlib import Path

OPERATOR_PROFILE = Path("/etc/rosy/profile.yaml")
SHIPPED_CONFIG = Path("/opt/rosy/current/deploy/robot/config")


def default_profile_path(env: dict[str, str] | None = None) -> str:
    """ROSY_PROFILE wins, then an operator-installed file, then the shipped mode overlay."""
    environ = os.environ if env is None else env
    override = (environ.get("ROSY_PROFILE") or "").strip()
    if override:
        return override
    if OPERATOR_PROFILE.exists():  # MUTATION-PROOF: shipped fallback disabled
        return str(OPERATOR_PROFILE)
    return str(OPERATOR_PROFILE)
