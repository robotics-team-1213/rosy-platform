#!/usr/bin/env python3
"""Device bring-up helpers for the native guard (split of `guarded_native.py`, D-766 2).

Owns the joint/bus constants and the passive connect / torque-off / close / sample
checks. `guarded_native` imports these back, so every existing importer
(`cell_envelope`, `chunk_runner`, tests) is unchanged.
"""
from __future__ import annotations

import math

TURN = 4096
TICKS_PER_DEGREE = TURN / 360
MAX_GAP_S = 0.5
MAX_STEP_S = 0.1
# one corrupt status packet on the shared hub ended three arm S sessions on 2026-10-27, once with the arm low;
# a read is safe to repeat, and a bus that is really gone still fails after the retries
READ_RETRY = 2
#: A torque-off servo follows its Present_Position with Goal_Position, so a seed write is
#: replaced within one sample and the readback can be one tick away from the next pose read.
SEED_TOLERANCE_TICKS = 1
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
NAMES = (*BODY, "gripper")
#: PWM_Limit admitted per body joint: the XL430 base, shoulder and elbow carry the arm at reach up to
#: record_session's XL430_PWM_MAX (2026-10-26: 78 % of 300 at 0.23 m); the XL330 wrist stays at 400.
PWM_ADMIT_MAX = {"shoulder_pan": 600, "shoulder_lift": 600, "elbow_flex": 600, "wrist_flex": 400, "wrist_roll": 400}
#: Session servo profile (record_session caps "acc"/"vel", raw X-series units: 21.46 deg/s^2, 1.374 deg/s) kept at
#: connect so the servo ramps between the whole-tick goals instead of snapping to each (2026-10-27: arm S shook on
#: 1-2 tick steps). Velocity >= 20.6 deg/s, twice the 10 deg/s this guard streams at most, so it never slows a stream;
#: acceleration >= 107 deg/s^2 adds a steady lag of v^2/2a <= 0.47 deg at 10 deg/s (0.06 at RISE_SPEED 3.6 deg/s)
#: against the 5 deg following-error bound. Anything else is cleared to 0 (step goals) as before.
PROFILE_ACC, PROFILE_VEL = (5, 100), (15, 200)
PROFILE = {"Profile_Acceleration": PROFILE_ACC, "Profile_Velocity": PROFILE_VEL}
#: Overload hold (2026-11-09 panel, after arm_a dropped extended when this guard cut torque on a wrist overload): the
#: first overload on a joint sets that joint's goal to where it stands, once, and keeps torque on. While any joint is
#: held every joint's command is frozen, so a runner that knows nothing of holds cannot carry the arm into a pose no
#: one checked; a runner built with `shed_load=True` may move the other joints to shed the load (cell_unwedge style).
#: A hold ends only by `release_hold()`, which that runner calls once its targets no longer push into the stall. The
#: watch is PWM alone, since a frozen goal zeroes the error: at 90 % of the cap for HOLD_S, a temperature rise of
#: HOLD_TEMP_RISE_C, a second overload on the joint in the session, or a failed read in the watch (temperature is read
#: each 0.2 s on held joints) ends the session with torque off as before. HOLD_S: no body joint has sat at the cap past
#: 3 s without a stop, and the one recorded latch (elbow wind-up, hw error 32) came after about 18 s.
HOLD_S, HOLD_TEMP_RISE_C = 3.0, 3


def torque_off(bus):
    """One failed motor must not prevent attempts on the remaining motors."""
    errors = []
    for name in bus.motors:
        try:
            bus.disable_torque(name, num_retry=2)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise RuntimeError(f"torque OFF not confirmed: {errors}")


def close_device(device):
    failures = []
    try:
        if device.bus.is_connected:
            try:
                torque_off(device.bus)
            except BaseException as exc:
                failures.append(exc)
            try:
                device.bus.disconnect()
            except BaseException as exc:
                failures.append(exc)
    finally:
        for camera in getattr(device, "cameras", {}).values():
            if camera.is_connected:
                camera.disconnect()
    if failures:
        # one message, not the last failure: the first is usually the cause
        raise RuntimeError("; ".join(str(failure) for failure in failures))


def connect_passive(device, *, follower):
    """Never call vendor configure/calibrate: those enable torque or write EEPROM."""
    bus = device.bus
    try:
        bus.connect()  # installed SDK handshake verifies each ID/model
        torque_off(bus)
        if not bus.calibration or not bus.is_calibrated:
            raise ValueError("calibration mismatch; commission with torque OFF before use")
        use_sync = "read" not in vars(bus) and hasattr(bus, "model_ctrl_table")
        modes = bus.sync_read("Operating_Mode", list(NAMES), normalize=False, num_retry=READ_RETRY) if use_sync else None
        hw_errs = bus.sync_read("Hardware_Error_Status", list(NAMES), normalize=False, num_retry=READ_RETRY) if use_sync else None
        torques = bus.sync_read("Torque_Enable", list(NAMES), normalize=False, num_retry=READ_RETRY) if use_sync else None
        prof_reads = ({r: bus.sync_read(r, list(NAMES), normalize=False, num_retry=READ_RETRY) for r in PROFILE}
                      if use_sync and follower else None)
        drive_modes = (bus.sync_read("Drive_Mode", list(NAMES), normalize=False, num_retry=READ_RETRY)
                       if use_sync and follower else None)
        for name in NAMES:
            calibration = bus.calibration[name]
            if calibration.range_min >= calibration.range_max:
                raise ValueError(f"{name}: invalid calibrated range")
            if name in BODY and (calibration.drive_mode != 0 or calibration.homing_offset != 0):
                raise ValueError(f"{name}: unsupported body calibration")
            mode = modes[name] if modes is not None else bus.read("Operating_Mode", name)
            if mode != (5 if name == "gripper" else 4):
                raise ValueError(f"{name}: expected commissioned mode 4 body / 5 gripper")
            err = hw_errs[name] if hw_errs is not None else bus.read("Hardware_Error_Status", name)
            tq = torques[name] if torques is not None else bus.read("Torque_Enable", name)
            if err or tq:
                raise ValueError(f"{name}: error or torque is ON")
            if follower:
                prof_ok = all(
                    low <= (prof_reads[r][name] if prof_reads is not None else bus.read(r, name)) <= high
                    for r, (low, high) in PROFILE.items()
                )
                if not (prof_ok and not (drive_modes[name] if drive_modes is not None else bus.read("Drive_Mode", name)) & 4):  # bit 2: time-based, other units
                    for register in PROFILE:
                        bus.write(register, name, 0)
                        if bus.read(register, name) != 0:
                            raise ValueError(f"{name}: {register} readback mismatch")
        for camera in getattr(device, "cameras", {}).values():
            camera.connect()
    except BaseException as exc:
        try:
            close_device(device)
        except BaseException as close_exc:
            # A latched motor error makes the closing torque-OFF fail too. Without this the
            # close error replaced the handshake error and the receipt named the wrong cause.
            if isinstance(exc, Exception):
                raise RuntimeError(f"{exc}; the close after it also failed: {close_exc}") from exc
        raise


def finite_values(values, names):
    if set(values) != set(names) or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                                        for v in values.values()):
        raise ValueError("missing or non-finite joint sample")


def normalized(bus, raw):
    values = bus._normalize({bus.motors[n].id: v for n, v in raw.items()})
    return {n + ".pos": values[bus.motors[n].id] for n in raw}

