"""Pinky Pro body for the sensing nodes. URDF first; calib param wins if it is sane.

D-424: the body (front/rear/half width/rotation radius, LiDAR pose) is the shared
core_common.robot_body.PINKY_PRO, the same one CORE line follow (D-422) and the PC
calibration tools use. Lidar sits on top of the chassis, so a live scan is walls, not the body.
"""
import math

from core_common.robot_body import PINKY_PRO as BODY

# URDF nominal (D-397: src/products/pinky_pro/profile/config/geometry.yaml, from
# rosy.urdf.xacro; drift-tested), metres, base_link origin. A calibrated
# robot_radius refines the radius below (use_radius), never under ROTATION_RADIUS for turns.
WHEEL_Y = 0.04055                 # wheels.joint_y_m
WHEEL_R = 0.028                   # wheels.radius_m
CASTER_X = 0.0585
CASTER_EXTRA = 0.011 + 0.0065     # CASTER_X + CASTER_EXTRA = -caster.rear_x_m
LIDAR_X = BODY.lidar_x_m          # lidar.x_m
FRONT_X = 0.0295                  # ir.mid.x_m (IR bar; the body front is BODY.front_x_m)
# Swept body radius for in-place rotation: footprint.rotation_radius_m (collision meshes).
ROTATION_RADIUS = BODY.rotation_radius_m

RADIUS_LO = 0.040
RADIUS_HI = 0.150


def urdf_radius() -> float:
    wheel = abs(WHEEL_Y) + WHEEL_R
    caster = CASTER_X + CASTER_EXTRA
    front = abs(FRONT_X)
    return max(wheel, caster, front)


# Wheel/caster circumradius (planning radius). D-424: in-place turns use rotation_radius(),
# never below ROTATION_RADIUS: the collision meshes (screen mount, corners) reach further.
URDF_RADIUS = urdf_radius()


def use_radius(calib, urdf: float | None = None) -> float:
    """Calib yaml/param if in range, else URDF."""
    base = URDF_RADIUS if urdf is None else float(urdf)
    try:
        c = float(calib)
    except (TypeError, ValueError):
        return base
    if c != c or c < RADIUS_LO or c > RADIUS_HI:
        return base
    return c


def ignore_m(radius: float) -> float:
    """Drop chassis-range lidar hits (from the C1, not base_link)."""
    front = FRONT_X - LIDAR_X
    return max(0.035, min(0.055, min(0.55 * float(radius), front - 0.006)))


def turn_clear_m(radius: float, margin: float = 0.010) -> float:
    """Free space needed beside the body to spin in place."""
    return float(radius) + float(margin)


def rotation_radius(calib) -> float:
    """D-424: radius for in-place rotation checks: a calibrated radius may grow it, never
    shrink it below the URDF rotation radius."""
    return max(use_radius(calib), ROTATION_RADIUS)


def footprint_bounds() -> tuple:
    """D-424: (rear, front, half width) of the URDF body for footprint_guard."""
    return BODY.box_bounds()
