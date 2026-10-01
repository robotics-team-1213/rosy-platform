"""Wheel geometry: URDF nominal < accepted calibration record < operator override.

The bringup parameters are the URDF nominal (rosy_params.yaml: 0.028 / 0.0971,
D-397 geometry.yaml). The operator-accepted ``wheel_odometry`` record in the
versioned calibration store (D-47 addendum 2026-10-01) refines them; without
one, or without core_common in the image, the parameters stand. An accepted
record outside the URDF nominal +-10 %, or holding a bool or non-number, is
refused by the store's check_values and the parameters stand. A positive
``override`` value (the bringup launch arguments wheel_radius /
wheel_separation; 0 or None = not set) wins over both. The returned source
line (which bringup logs) says which applied. ROS-free.
"""


def calibrated_wheels(wheel_radius, wheel_separation, *, override=None, root=None, robot=None):
    static = {'wheel_radius': float(wheel_radius), 'wheel_separation': float(wheel_separation)}
    chosen = {k: float(v) for k, v in (override or {}).items()
              if k in static and v is not None and float(v) > 0.0}
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
