"""core_common.profile — HWA-001 Robot Profile 로더 (P1-15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

#: D-196: the robot package CORE loads when nothing names one.
DEFAULT_ROBOT = "pinky_pro"


def robot_config_dir(robot: str) -> Path:
    """Config directory of the robot package ``robot`` (D-196).

    The installed ament share wins; a host checkout falls back to src/robots/<robot>/config.
    """
    try:
        from ament_index_python.packages import get_package_share_directory
        return Path(get_package_share_directory(robot)) / "config"
    except Exception:
        return Path(__file__).resolve().parents[3] / "robots" / robot / "config"


class RobotProfile:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data.get("profile", data)

    @classmethod
    def load(cls, path: Path) -> "RobotProfile":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    @property
    def model(self) -> str:
        return str(self._data.get("model", "unknown"))

    @property
    def max_linear_velocity(self) -> Optional[float]:
        v = self._data.get("max_linear_velocity")
        return float(v) if v is not None else None

    @property
    def max_angular_velocity(self) -> Optional[float]:
        v = self._data.get("max_angular_velocity")
        return float(v) if v is not None else None
