"""Wheel geometry from the versioned calibration store (D-47 addendum 2026-10-01).

The operator-accepted ``wheel_odometry`` record wins over the bringup
parameters (rosy_params.yaml: 0.027 / 0.0961, the seed); without one, or
without core_common in the image, the parameters stand. An accepted record
outside 0.027 m / 0.0961 m +-10 %, or holding a bool or non-number, is
refused by the store's check_values and the parameters stand; the returned
source line (which bringup logs) says so. ROS-free.
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
