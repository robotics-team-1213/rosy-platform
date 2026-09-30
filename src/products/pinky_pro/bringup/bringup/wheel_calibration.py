"""Wheel geometry from the versioned calibration store (D-47 addendum 2026-10-01).

The operator-accepted ``wheel_odometry`` record wins over the bringup
parameters (rosy_params.yaml: 0.027 / 0.0961, the seed); without one, or
without core_common in the image, the parameters stand. Returns the values
and the source line bringup logs. ROS-free.
"""


def calibrated_wheels(wheel_radius, wheel_separation, *, root=None, robot=None):
    static = {'wheel_radius': float(wheel_radius), 'wheel_separation': float(wheel_separation)}
    try:
        from core_common.calibration_store import resolve
    except ImportError:
        return static, 'bringup parameters (calibration store unavailable)'
    values, source = resolve('wheel_odometry', static, fallback_source='bringup parameters',
                             root=root, robot=robot)
    return {k: float(values[k]) for k in static}, source
