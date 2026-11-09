"""D-1005: operator speed settings under the signed ceiling, and the sealed measured speed CORE binds to.

The ceiling is the profile's hardware limit (SpeedLimits.max_linear/max_angular). A value above it is
refused, never clipped, so what the operator set is what runs.
"""
from __future__ import annotations

import math

from core_features.safety_gate.limits import SpeedLimits

TRAVEL_RUN_CEILING_M = 0.25  # approval_trials.TRAVEL_RUN_CEILING_M; test_speed_limit_config pins the pair

# request name -> (SpeedLimits field, ceiling field or fixed ceiling, may be zero)
SETTINGS = {
    "manual_linear": ("manual_linear", "max_linear", True),
    "manual_angular": ("manual_angular", "max_angular", True),
    "trial_linear": ("approval_linear", "max_linear", False),
    "trial_angular": ("approval_angular", "max_angular", False),
    "trial_travel_m": ("approval_travel_m", TRAVEL_RUN_CEILING_M, False),
}


class SpeedSettingError(ValueError):
    pass


def validate(request: dict, limits: SpeedLimits) -> dict:
    """{limits field: value} for every setting in the request, or SpeedSettingError for the first bad one."""
    out = {}
    for name, value in request.items():
        field, ceiling, zero_ok = SETTINGS[name]
        top = ceiling if isinstance(ceiling, float) else getattr(limits, ceiling)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SpeedSettingError(f"{name} must be a finite number")
        if value < 0 or (value == 0 and not zero_ok):
            raise SpeedSettingError(f"{name} must be {'zero or ' if zero_ok else ''}positive")
        if value > top:
            raise SpeedSettingError(f"{name} {value} is above the signed ceiling {top}")
        out[field] = float(value)
    return out


def apply(limits: SpeedLimits, values: dict) -> dict:
    """Set the validated values; returns {field: [old, new]} for the audit record."""
    changes = {field: [getattr(limits, field), value] for field, value in values.items()}
    for field, value in values.items():
        setattr(limits, field, value)
    return changes


def sealed_speeds(approval: dict | None) -> tuple[float, float] | None:
    """The measured speeds of a valid approval from the host reply; None when it carries none."""
    if not isinstance(approval, dict) or approval.get("valid") is not True:
        return None
    linear, angular = approval.get("measured_linear_mps"), approval.get("measured_angular_rps")
    for value in (linear, angular):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return None
    return float(linear), float(angular)
