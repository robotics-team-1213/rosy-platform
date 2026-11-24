#!/usr/bin/env python3
"""Out-of-Band Hardware Error, Held-Overload & Monitor Limit Probes (`guarded_native_probe.py`).

Single Responsibility:
  - Poll hardware error flags and held-joint thermal/PWM-saturation deadlines during encoder-read HOLDs.
  - Enforce MotorHealth configured limits across runner health polls and interrupt HOLDs without unhandled exceptions.
"""
from __future__ import annotations

import math

from guarded_device import (
    HOLD_S,
    HOLD_TEMP_RISE_C,
    MAX_GAP_S,
    NAMES,
    torque_off,
)


def safe_print(text: str) -> None:
    """Best-effort stdout diagnostic: closed or broken stdout must never trigger torque OFF."""
    try:
        print(text, flush=True)
    except Exception:  # noqa: BLE001
        pass


class TelemetryReadError(ValueError):
    """Recoverable invalid/unavailable telemetry; triggers HOLD when hold_on_read_error=True, torque-OFF otherwise."""

    recoverable_telemetry = True


HW_ERROR_VALID_MASK = 0x3D  # XL430/XL330 Hardware_Error_Status bits 0,2,3,4,5 (bits 1,6,7 are always 0 in firmware)


def drain_rx(bus) -> None:
    """Best-effort serial RX clear after a Protocol 2.0 framing/transaction desync."""
    clear = getattr(getattr(bus, "port_handler", None), "clearPort", None)
    if callable(clear):
        try:
            clear()
        except Exception:  # noqa: BLE001
            pass


def sync_read_torque_enable(bus) -> dict:
    """Read Torque_Enable across motors, draining RX and retrying once if Write-Ack CRC bytes leak into readback."""
    res = dict(bus.sync_read("Torque_Enable", normalize=False, num_retry=2))
    if any(not (type(v) is int and v in (0, 1)) for v in res.values()):
        drain_rx(bus)
        res = dict(bus.sync_read("Torque_Enable", normalize=False, num_retry=2))
    return res


def check_sync_hw_status(follower, errors, read_retry: int) -> None:
    """Validate sync_read Hardware_Error_Status dict, draining RX and confirming real fault bits via unicast."""
    if not isinstance(errors, dict):
        raise TelemetryReadError("missing or non-finite joint sample")
    for name in NAMES:
        if name not in errors or not is_valid_hw_status(errors.get(name)):
            drain_rx(follower)
            raise TelemetryReadError(f"desynced hardware status {errors}")
    for name in NAMES:
        val = errors[name]
        if not is_hardware_fault(val):
            continue
        if getattr(follower, "port_handler", None) is not None and callable(getattr(follower, "read", None)):
            drain_rx(follower)
            confirm = follower.read("Hardware_Error_Status", name, num_retry=read_retry)
            if confirm == 0:
                raise TelemetryReadError(f"{name}: transient desynced hardware status {errors}")
            if not is_valid_hw_status(confirm):
                drain_rx(follower)
                raise TelemetryReadError(f"{name}: invalid hardware status {confirm}")
            val = confirm
        raise ValueError(f"{name}: hardware error ({val}; all={errors})")


def is_valid_hw_status(val) -> bool:
    return type(val) is int and 0 <= val <= 255 and (val & ~HW_ERROR_VALID_MASK) == 0


def is_hardware_fault(val) -> bool:
    return type(val) is int and 0 < val <= 255 and (val & ~HW_ERROR_VALID_MASK) == 0


def is_recoverable_telemetry(exc: BaseException) -> bool:
    if not isinstance(exc, ValueError):
        return True
    if getattr(exc, "recoverable_telemetry", False):
        return True
    msg = str(exc)
    return "stale" in msg or "missing or non-finite joint sample" in msg


def probe_hardware_errors(motion) -> None:
    """Confirm no responding motor reports a hardware fault before converting a read/sample error into HOLD."""
    try:
        motion._check_hardware_errors()
        return
    except (OSError, TimeoutError, ConnectionError):
        pass
    except ValueError as err:
        if not is_recoverable_telemetry(err):
            raise
    read = getattr(motion.follower, "read", None)
    if not callable(read):
        return
    for name in NAMES:
        try:
            val = read("Hardware_Error_Status", name)
        except (OSError, TimeoutError, ConnectionError):
            continue
        if is_hardware_fault(val):
            raise ValueError(f"{name}: hardware error ({val})")


def _last_hold_telemetry(motion, hold: dict, now: float) -> float:
    last = hold.get("last_telemetry_at")
    if isinstance(last, (int, float)) and not isinstance(last, bool) and math.isfinite(last):
        return last
    since = hold.get("since")
    since_ok = isinstance(since, (int, float)) and not isinstance(since, bool) and math.isfinite(since)
    et = getattr(motion, "last_effort_time", None)
    if (isinstance(et, (int, float)) and not isinstance(et, bool) and math.isfinite(et)
            and et <= now and (not since_ok or et >= since)):
        return et
    return since if since_ok and since <= now else now


def check_hold_deadlines(motion, name: str, hold: dict, now: float, *, pwm=None) -> None:
    """Enforce HOLD_S on both recorded saturation and age since the last valid (PWM, temperature) pair."""
    last = _last_hold_telemetry(motion, hold, now)
    if not 0 <= now - last < HOLD_S - 1e-9:
        raise ValueError(
            f"{name}: overload risk; held joint telemetry gap {now - last:.2f}s >= {HOLD_S:.1f}s "
            f"duration={now - hold['since']:.2f}s"
        )
    sat = hold.get("saturated_since")
    if sat is not None and not 0 <= now - sat < HOLD_S - 1e-9:
        limits = getattr(motion, "pwm_limits", None) or {}
        detail = f" at PWM={pwm} limit={limits.get(name, 'gripper current mode')}" if pwm is not None and (name in limits or name == "gripper") else ""
        raise ValueError(
            f"{name}: overload risk; hold timed out{detail} duration={now - hold['since']:.2f}s"
        )


def probe_held_overload(motion) -> None:
    """Keep held-joint thermal and saturation protection active even when encoder reads fail."""
    read_started = motion.clock()
    for name, since in (getattr(motion, "effort_since", None) or {}).items():
        if since is not None and not 0 <= read_started - since < 1.0 + HOLD_S - 1e-9:
            raise ValueError(
                f"{name}: overload risk; saturated joint telemetry lost past {HOLD_S:.1f}s cap "
                f"duration={read_started - since:.2f}s"
            )
    if getattr(motion, "held", None) and getattr(motion, "pwm_limits", None):
        pwms = {}
        try:
            raw_pwms = motion._read_body_pwm()
            if isinstance(raw_pwms, dict):
                pwms = raw_pwms
        except (OSError, TimeoutError, ConnectionError):
            pass
        read = getattr(motion.follower, "read", None)
        for name in list(motion.held):
            if name not in motion.pwm_limits:
                continue
            hold = motion.held[name]
            pwm = pwms.get(name)
            if (pwm is None or isinstance(pwm, bool) or not isinstance(pwm, (int, float))
                    or not math.isfinite(pwm)) and callable(read):
                try:
                    pwm = read("Present_PWM", name)
                except (OSError, TimeoutError, ConnectionError):
                    pwm = None
            valid_pwm = not isinstance(pwm, bool) and isinstance(pwm, (int, float)) and math.isfinite(pwm)
            if valid_pwm:
                saturated = abs(pwm) >= 0.9 * motion.pwm_limits[name]
                try:
                    motion._watch_hold(name, saturated, pwm, read_started)
                except (OSError, TimeoutError, ConnectionError):
                    now = motion.clock()
                    check_hold_deadlines(motion, name, hold, now, pwm=pwm)
                    if not saturated:
                        if 0 <= now - read_started <= MAX_GAP_S:
                            hold["saturated_since"] = None
                    elif hold["saturated_since"] is None:
                        hold["saturated_since"] = min(read_started, now)
            else:
                temp = None
                if callable(read):
                    try:
                        temp = read("Present_Temperature", name)
                    except (OSError, TimeoutError, ConnectionError):
                        temp = None
                now = motion.clock()
                if not isinstance(temp, bool) and isinstance(temp, (int, float)) and math.isfinite(temp):
                    check_temp_limit(motion, name, temp)
                    if temp - hold["temp"] >= HOLD_TEMP_RISE_C:
                        raise ValueError(
                            f"{name}: overload risk; held joint warmed {temp - hold['temp']} C "
                            f"duration={now - hold['since']:.2f}s"
                        )
                check_hold_deadlines(motion, name, hold, now)
    probe = getattr(getattr(motion, "monitor", None), "probe_limits", None)
    if callable(probe):
        probe(motion)


def check_temp_limit(motion, name: str, temp: float) -> None:
    """Enforce any admitted MotorHealth configured temperature_limit_c on the first valid reading."""
    check = getattr(getattr(motion, "monitor", None), "check_temperature", None)
    if callable(check):
        check(motion, name, temp)


def _run_monitor_gate(motion, fn, *args) -> None:
    """Run an external monitor check and cut torque OFF immediately if a hard limit fails."""
    try:
        fn(*args)
    except BaseException as exc:
        motion.failed = True
        try:
            torque_off(motion.follower)
        finally:
            motion.report_fault(exc)
        raise


def enforce_temperatures(motion, temps: dict) -> None:
    """Route external runner temperature readings through admitted MotorHealth limits and guard torque-off."""
    check = getattr(getattr(motion, "monitor", None), "check_temperature", None)
    if motion is None or not isinstance(temps, dict) or not callable(check):
        return
    for name, temp in temps.items():
        _run_monitor_gate(motion, check, motion, name, temp)


def probe_runner_limits(motion) -> None:
    """Before absorbing a runner health read error into HOLD, verify no responding motor exceeds hard limits."""
    probe = getattr(getattr(motion, "monitor", None), "probe_limits", None)
    if motion is not None and not getattr(motion, "failed", False) and callable(probe):
        _run_monitor_gate(motion, probe, motion)


def check_hold_health(runner, motors) -> None:
    """Poll runner health during signal-driven HOLD and route any thermal/hard-limit fault to guard torque-off."""
    motion = getattr(getattr(runner, "robot", None), "motion", None)
    read_health = getattr(runner, "read_health", None)
    if callable(read_health):
        try:
            health = read_health()
        except Exception:  # noqa: BLE001
            probe_runner_limits(motion)
            raise
        if isinstance(health, dict) and isinstance(health.get("temp_c"), (list, tuple)):
            enforce_temperatures(motion, dict(zip(motors, health["temp_c"])))
    probe_runner_limits(motion)
