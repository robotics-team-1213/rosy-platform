"""Heat mode: how hot the robot is decides how fast it may drive. ROS-free.

Inputs are what a Raspberry Pi robot can read about itself: the SoC temperature, the Pi
firmware's throttle bits, and per wheel motor the temperature, the motor's own limit and its
hardware-error register (the bringup node's `motor/health`).

Levels, worst wins:

- ``hot``: SoC at ``soc_hot_c``, a motor within ``motor_hot_margin_c`` of its limit, or a
  motor already reporting overheating. Fleet and navigation commands go to zero; manual
  driving keeps the warm cap so an operator can still nudge the robot off the lane.
- ``warm``: SoC at ``soc_warm_c``, a motor within ``motor_warm_margin_c`` of its limit, the
  firmware throttling or capping now, under-voltage now, or a motor input-voltage error.
  Linear speed is scaled by ``warm_linear_scale``.
- ``ok``: everything else, including no readings at all (unknown is not hot).

A level is left only once every reading is ``clear_c`` below the threshold that raised it,
so a temperature sitting on a threshold does not toggle the speed cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional

OK, WARM, HOT = "ok", "warm", "hot"
_RANK = {OK: 0, WARM: 1, HOT: 2}

# Raspberry Pi get_throttled bits that are true *now* (16-19 are "since boot").
THROTTLE_UNDER_VOLTAGE = 0x1
THROTTLE_FREQ_CAPPED = 0x2
THROTTLE_THROTTLED = 0x4
THROTTLE_SOFT_TEMP_LIMIT = 0x8
# DYNAMIXEL X hardware-error bits.
MOTOR_INPUT_VOLTAGE = 0x01
MOTOR_OVERHEATING = 0x04


@dataclass(frozen=True)
class ThermalPolicy:
    soc_warm_c: float = 75.0        # the Pi 5 fan's top trip point; firmware soft-throttles at 80
    soc_hot_c: float = 82.0
    motor_warm_margin_c: float = 10.0
    motor_hot_margin_c: float = 4.0
    clear_c: float = 5.0
    warm_linear_scale: float = 0.5
    motor_stale_s: float = 10.0     # five missed motor/health samples: the reading no longer counts

    def __post_init__(self) -> None:
        values = (self.soc_warm_c, self.soc_hot_c, self.motor_warm_margin_c, self.motor_hot_margin_c,
                  self.clear_c, self.warm_linear_scale, self.motor_stale_s)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError("thermal policy values must be finite numbers")
        if not (self.soc_warm_c < self.soc_hot_c and self.motor_hot_margin_c < self.motor_warm_margin_c):
            raise ValueError("thermal policy: hot must be above warm")
        if not 0 <= self.warm_linear_scale <= 1 or self.clear_c < 0 or self.motor_stale_s <= 0:
            raise ValueError("thermal policy: scale in [0, 1], clear >= 0, stale > 0")

    @classmethod
    def from_config(cls, safety_cfg: dict) -> "ThermalPolicy":
        cfg = (safety_cfg or {}).get("thermal") or {}
        return cls(**{k: float(v) for k, v in cfg.items() if k in cls.__dataclass_fields__})


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


@dataclass
class ThermalMonitor:
    policy: ThermalPolicy = field(default_factory=ThermalPolicy)
    level: str = OK
    reasons: tuple = ()
    soc_c: Optional[float] = None
    throttled: Optional[int] = None
    motors: list = field(default_factory=list)
    _motors_at: Optional[float] = None
    _source_levels: dict = field(default_factory=dict, init=False, repr=False)

    def on_motor_health(self, payload, now: float) -> None:
        """Store one `motor/health` sample; malformed rows are dropped, not trusted."""
        rows = payload.get("motors") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return
        kept = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            error = row.get("hardware_error")
            kept.append({"id": row.get("id"),
                         "temperature_c": _number(row.get("temperature_c")),
                         "temperature_limit_c": _number(row.get("temperature_limit_c")),
                         "input_voltage_v": _number(row.get("input_voltage_v")),
                         "hardware_error": error if isinstance(error, int) and not isinstance(error, bool) else None})
        self.motors, self._motors_at = kept, now

    def update(self, soc_c, throttled, now: float) -> str:
        """Re-evaluate with the latest SoC reading; returns the new level."""
        self.soc_c = _number(soc_c)
        self.throttled = throttled if isinstance(throttled, int) and not isinstance(throttled, bool) else None
        p = self.policy
        fresh = self._motors_at is not None and now - self._motors_at <= p.motor_stale_s
        motors = self.motors if fresh else []
        reasons: list[tuple[str, str]] = []
        known: dict[str, bool] = {}

        def over(level: str, value: Optional[float], threshold: float, reason: str) -> None:
            known[reason] = value is not None
            # Hysteresis: holding this level (or a worse one) lowers the bar by clear_c.
            bar = threshold - (p.clear_c if _RANK[self.level] >= _RANK[level] else 0.0)
            if value is not None and value >= bar:
                reasons.append((level, reason))

        over(HOT, self.soc_c, p.soc_hot_c, "soc_hot")
        over(WARM, self.soc_c, p.soc_warm_c, "soc_warm")
        for m in motors:
            limit, temp = m["temperature_limit_c"], m["temperature_c"]
            if limit is not None:
                over(HOT, temp, limit - p.motor_hot_margin_c, f"motor_{m['id']}_hot")
                over(WARM, temp, limit - p.motor_warm_margin_c, f"motor_{m['id']}_warm")
            error = m["hardware_error"]
            for suffix in ("overheating", "input_voltage"):
                known[f"motor_{m['id']}_{suffix}"] = error is not None
            error = error or 0
            if error & MOTOR_OVERHEATING:
                reasons.append((HOT, f"motor_{m['id']}_overheating"))
            if error & MOTOR_INPUT_VOLTAGE:
                reasons.append((WARM, f"motor_{m['id']}_input_voltage"))
        bits = self.throttled or 0
        for bit, reason in ((THROTTLE_UNDER_VOLTAGE, "under_voltage"), (THROTTLE_FREQ_CAPPED, "freq_capped"),
                            (THROTTLE_THROTTLED, "throttled"), (THROTTLE_SOFT_TEMP_LIMIT, "soft_temp_limit")):
            if bits & bit:
                reasons.append((WARM, reason))
        # A reading that raised the level and then vanished (a hot motor stops answering, the
        # probe fails) holds that source's own severity until its required reading returns.
        # Motor temperature reasons need both temperature and limit; another motor cannot clear them.
        held = [(level, reason) for reason, level in self._source_levels.items() if not known.get(reason, False)]
        reasons.extend(held)
        level = max((level for level, _ in reasons), key=_RANK.__getitem__, default=OK)
        self._source_levels = {reason: severity for severity, reason in reasons
                               if reason.startswith(("soc_", "motor_"))}
        if held:
            reasons.append((level, "readings_lost"))
        self.level = level
        self.reasons = tuple(dict.fromkeys(reason for _, reason in reasons))
        return self.level

    def caps(self, max_linear: float, max_angular: float, scope: str) -> tuple[float, float]:
        """The (linear, angular) caps after heat: lowered only, never raised."""
        if self.level == HOT and scope != "manual":
            return 0.0, 0.0           # no spinning in place either
        if self.level in (WARM, HOT):
            return max_linear * self.policy.warm_linear_scale, max_angular
        return max_linear, max_angular

    def status(self) -> dict:
        return {"level": self.level, "reasons": list(self.reasons), "soc_c": self.soc_c,
                "throttled": self.throttled, "motors": list(self.motors)}
