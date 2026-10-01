"""Wheel geometry: URDF nominal < accepted calibration record < operator override.

The bringup parameters are the URDF nominal (rosy_params.yaml: 0.028 / 0.0971,
D-397 geometry.yaml). The operator-accepted ``wheel_odometry`` record in the
versioned calibration store (D-47 addendum 2026-10-01) refines them; without
one, or without core_common in the image, the parameters stand. An accepted
record outside the URDF nominal +-10 %, or holding a bool or non-number, is
refused by the store's check_values and the parameters stand. A positive
``override`` value (the bringup launch arguments wheel_radius /
wheel_separation; 0 or None = not set) wins over both, provided it passes
the same plausibility check as a record; a NaN or negative override is
dropped and reported through ``log``. The returned source line (which
bringup logs) says which applied. ROS-free.
"""
import math


def calibrated_wheels(wheel_radius, wheel_separation, *, override=None, root=None, robot=None,
                      log=None):
    static = {'wheel_radius': float(wheel_radius), 'wheel_separation': float(wheel_separation)}
    chosen = {}
    for key, value in (override or {}).items():
        number = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else math.nan
        if key in static and math.isfinite(number) and number > 0.0:
            chosen[key] = number
        elif value not in (None, 0, 0.0) and log is not None:
            log(f'wheel override {key}={value!r} dropped: not a positive finite number')
    try:
        from core_common.calibration_store import resolve
    except ImportError:
        source = 'bringup parameters (calibration store unavailable)'
        if chosen:
            source += f"; operator override {', '.join(sorted(chosen))}"
        return {**static, **chosen}, source
    values, source = resolve('wheel_odometry', static, fallback_source='bringup parameters',
                             root=root, robot=robot, override=chosen)
    return {k: float(values[k]) for k in static}, source
