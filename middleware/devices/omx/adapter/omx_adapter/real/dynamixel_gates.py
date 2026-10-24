"""D-858 S1/S3 motion-gate values: measured evidence, V-016 stop bounds, tracking, grasp spec.
Moved out of ``dynamixel_port.py`` (D-766 size limit)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

# V-016 user-confirmed stop bounds, the D-858 §4 starting point: the arm stops within
# 500 ms of the stop and joint1 stays within 0.1 rad of where it was, slower than 0.1 rad/s.
MAX_STOP_MS = 500
MAX_JOINT1_DEVIATION_RAD = 0.1
MAX_JOINT1_VELOCITY_RAD_S = 0.1
# V-016 stop-test motion: small and slow (device-core STOP_TEST_RULES bounds).
STOP_TEST_MAX_AMPLITUDE_RAD = 0.2
STOP_TEST_MAX_SPEED_RAD_S = 0.2


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _within(value: object, bound: float) -> bool:
    return _finite(value) and 0 <= value <= bound


@dataclass(frozen=True)
class MotionEvidence:
    """D-858 §4 gate inputs, loaded from the S3 commissioning record (``commissioning_record``).

    ``revision`` is the record's content hash; the port HOLDs when the stored record moves on.
    ``config_revision`` is the ``ArmCommandConfig.calibration_revision`` the record was measured
    against; the port refuses motion under any other config. ``refusals`` are loader reasons."""

    limits_measured: bool = False
    gripper_open_rad: Optional[float] = None
    gripper_close_rad: Optional[float] = None
    # {passed, driver, config_revision, measured_stop_ms, joint1_deviation_rad, joint1_velocity_rad_s}
    stop_test: Optional[Mapping[str, object]] = None
    # TCP box ((x_min, x_max), (y_min, y_max), (z_min, z_max)) [m] in link0 (device-core
    # Limits.workspace). Measured on the bench: desk, tray, robot position.
    workspace_m: Optional[Sequence[Sequence[float]]] = None
    config_revision: Optional[str] = None
    revision: Optional[str] = None
    refusals: tuple[str, ...] = ()

    def blockers(self, *, config_revision: Optional[str] = None,
                 include_stop_test: bool = True) -> list[str]:
        """Empty means motion may run. ``include_stop_test=False`` is the measurement-mode gate
        the stop test itself runs under (D-858 §5 S3)."""
        out = list(self.refusals)
        if not self.revision:
            out.append("evidence not loaded from a commissioning record")
        if config_revision is not None and self.config_revision != config_revision:
            out.append(f"record measured against config revision {self.config_revision!r}, "
                       f"port config is {config_revision!r}")
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
        if include_stop_test:
            out.extend(self.stop_test_blockers())
        return out

    def stop_test_blockers(self) -> list[str]:
        """Re-check V-016 from the measured numbers; the recorded verdict alone is not enough."""
        st = self.stop_test or {}
        if not st:
            return ["no stop test record"]
        out = []
        if (st.get("passed") is not True or st.get("driver") != "dynamixel"
                or not _within(st.get("measured_stop_ms"), MAX_STOP_MS)
                or not _finite(st.get("joint1_deviation_rad"))
                or not _within(abs(st["joint1_deviation_rad"]), MAX_JOINT1_DEVIATION_RAD)
                or not _finite(st.get("joint1_velocity_rad_s"))
                or not _within(abs(st["joint1_velocity_rad_s"]), MAX_JOINT1_VELOCITY_RAD_S)):
            out.append(f"stop test record did not pass on this driver (V-016: <= {MAX_STOP_MS} ms, "
                       f"joint1 +-{MAX_JOINT1_DEVIATION_RAD} rad, {MAX_JOINT1_VELOCITY_RAD_S} rad/s)")
        if not self.config_revision or st.get("config_revision") != self.config_revision:
            out.append("stop test not run under the record's config revision")
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
