"""SAF-004 speed limits and SAF-005 thresholds as plain settings. Split from manager.py for its size budget (D-766)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeedLimits:
    max_linear: float = 0.20
    max_angular: float = 0.80
    manual_linear: float = 0.15
    manual_angular: float = 0.60
    fleet_linear: float = 0.20
    fleet_angular: float = 0.80

    @classmethod
    def from_config(cls, *, profile, nav_cfg: dict, safety_cfg: dict) -> "SpeedLimits":
        """프로필이 있으면 그걸 쓰고, 없으면 rosy.yaml navigation/safety 폴백."""
        nav_cfg = nav_cfg or {}
        safety_cfg = safety_cfg or {}
        max_linear = float(profile.max_linear_velocity or nav_cfg.get("max_linear_velocity") or cls.max_linear)
        max_angular = float(profile.max_angular_velocity or nav_cfg.get("max_angular_velocity") or cls.max_angular)
        return cls(
            max_linear=max_linear,
            max_angular=max_angular,
            manual_linear=float(safety_cfg.get("manual_linear", cls.manual_linear)),
            manual_angular=float(safety_cfg.get("manual_angular", cls.manual_angular)),
            fleet_linear=float(safety_cfg.get("fleet_linear", max_linear)),
            fleet_angular=float(safety_cfg.get("fleet_angular", max_angular)),
        )


@dataclass
class BatteryPolicy:
    warning_percent: float = 20.0
    critical_percent: float = 10.0
    critical_action: str = "RETURN_HOME"
