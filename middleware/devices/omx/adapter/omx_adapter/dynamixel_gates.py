"""D-858 S1 motion-gate values: measured evidence, tracking bounds, grasp check spec.
Moved out of ``dynamixel_port.py`` (D-766 size limit)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

# V-016 user-confirmed stop bound, the D-858 §4 starting point.
MAX_STOP_MS = 500


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)



@dataclass(frozen=True)
class MotionEvidence:
    """D-858 §4 gate inputs. S3 commissioning writes them; absent means measurement mode."""

    limits_measured: bool = False
    gripper_open_rad: Optional[float] = None
    gripper_close_rad: Optional[float] = None
    stop_test: Optional[Mapping[str, object]] = None  # {passed, driver, measured_stop_ms}
    # TCP box ((x_min, x_max), (y_min, y_max), (z_min, z_max)) [m] in link0 (device-core
    # Limits.workspace). Measured on the bench: desk, tray, robot position.
    workspace_m: Optional[Sequence[Sequence[float]]] = None

    def blockers(self) -> list[str]:
        out = []
        if self.limits_measured is not True:
            out.append("joint limits not measured on the real arm")
        grip = (self.gripper_open_rad, self.gripper_close_rad)
        if not all(_finite(v) for v in grip):
            out.append("gripper open/close values not measured")
        elif not all(-math.pi < v < math.pi for v in grip) or grip[0] == grip[1]:
            out.append("gripper open/close values must differ and lie inside (-pi, pi)")
        box = self.workspace_m
        if not (isinstance(box, (list, tuple)) and len(box) == 3 and all(
                isinstance(pair, (list, tuple)) and len(pair) == 2
                and all(_finite(v) for v in pair) and pair[0] < pair[1] for pair in box)):
            out.append("workspace box not measured")
        st = self.stop_test or {}
        stop_ms = st.get("measured_stop_ms")
        if not st:
            out.append("no stop test record")
        elif (st.get("passed") is not True or st.get("driver") != "dynamixel"
              or type(stop_ms) not in (int, float) or not 0 <= stop_ms <= MAX_STOP_MS):
            out.append("stop test record did not pass on this driver")
        return out


@dataclass(frozen=True)
class Tracking:
    """V-005 5 tracking bounds; replaced by measured values in commissioning."""

    period_s: float = 0.02
    max_tracking_rad: float = 0.2
    arrive_rad: float = 0.05
    arrive_s: float = 1.0

    def __post_init__(self) -> None:
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0
                   for v in (self.period_s, self.max_tracking_rad, self.arrive_rad, self.arrive_s)):
            raise ValueError("tracking bounds must be finite and positive")



def _validate_grasp(spec: object) -> None:
    keys = {"position_rad", "current_ma", "stable_rad", "samples", "period_s"}
    if not isinstance(spec, Mapping) or set(spec) != keys:
        raise ValueError("grasp_check needs position_rad/current_ma/stable_rad/samples/period_s")
    for key in ("position_rad", "current_ma"):
        pair = spec[key]
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or not all(type(v) in (int, float) and math.isfinite(v) for v in pair)
                or not pair[0] < pair[1]):
            raise ValueError(f"grasp_check.{key} needs a finite [min, max]")
    if (spec["current_ma"][0] <= 0 or type(spec["samples"]) is not int
            or not 2 <= spec["samples"] <= 1000
            or not all(type(spec[k]) in (int, float) and math.isfinite(spec[k]) and spec[k] > 0
                       for k in ("stable_rad", "period_s"))):
        raise ValueError("grasp_check needs positive current/stability/period and samples 2..1000")
