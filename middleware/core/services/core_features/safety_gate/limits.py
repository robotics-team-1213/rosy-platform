"""SAF-004 speed limits and SAF-005 thresholds as plain settings. Split from manager.py for its size budget (D-766)."""

from __future__ import annotations

from dataclasses import dataclass


def _optional(cfg: dict, key: str) -> float | None:
    """A sealed speed, or None. A value that is not a positive finite number is refused: min(x, nan) would bind nothing."""
    if cfg.get(key) is None:
        return None
    value = float(cfg[key])
    if not 0 < value < float("inf"):
        raise ValueError(f"safety.{key} must be a positive finite number, got {cfg[key]!r}")
    return value


@dataclass
class SpeedLimits:
    max_linear: float = 0.20
    max_angular: float = 0.80
    manual_linear: float = 0.15
    manual_angular: float = 0.60
    fleet_linear: float = 0.20
    fleet_angular: float = 0.80
    # D-1005: speeds a re-approval measured and sealed (None: no approval carries one, nothing binds),
    # the speed the running approval trial may use, and the operator's trial settings.
    approved_linear: float | None = None
    approved_angular: float | None = None
    trial_cap: tuple[float, float] | None = None
    approval_linear: float = 0.02
    approval_angular: float = 0.07
    approval_travel_m: float = 0.06

    def approved_caps(self) -> tuple[float, float]:
        """Driving never exceeds a sealed measured speed; the trial that re-measures may use its own."""
        if self.trial_cap is not None:
            return self.trial_cap
        return (float("inf") if self.approved_linear is None else self.approved_linear,
                float("inf") if self.approved_angular is None else self.approved_angular)

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
            approved_linear=_optional(safety_cfg, "approved_linear"),
            approved_angular=_optional(safety_cfg, "approved_angular"),
            approval_linear=float(safety_cfg.get("approval_linear", cls.approval_linear)),
            approval_angular=float(safety_cfg.get("approval_angular", cls.approval_angular)),
            approval_travel_m=float(safety_cfg.get("approval_travel_m", cls.approval_travel_m)),
        )


@dataclass
class BatteryPolicy:
    warning_percent: float = 20.0
    critical_percent: float = 10.0
    critical_action: str = "RETURN_HOME"
