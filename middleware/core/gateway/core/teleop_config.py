"""SAF-002 teleop watchdog setting (`safety.teleop_timeout_ms`), validated for CORE."""
from __future__ import annotations

#: SAF-002 watchdog bounds: below 100 ms a 10 Hz teleop client trips it between
#: two commands; above 2 s a lost link keeps the wheels turning too long.
TELEOP_TIMEOUT_MS_RANGE = (100, 2000)


def teleop_timeout_ms(safety_cfg) -> int:
    """`safety.teleop_timeout_ms` (SAF-002 "설정 가능"), validated; 500 when absent."""
    raw = (safety_cfg or {}).get("teleop_timeout_ms", 500)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != int(raw):
        raise ValueError(f"safety.teleop_timeout_ms must be a whole number of ms, got {raw!r}")
    low, high = TELEOP_TIMEOUT_MS_RANGE
    if not low <= int(raw) <= high:
        raise ValueError(f"safety.teleop_timeout_ms must be within {low}-{high} ms, got {raw}")
    return int(raw)
