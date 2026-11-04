"""Per-arm leveling spots and the D-956 seat check of a released box (split from mapped_stack_fixture, D-766)."""
import math

from pad_sweep import rotation_matrix


def seat_check(box, target, limits):
    """D-956 seat check of a released box: height above its target and tilt within the limits ({height_m, tilt_rad})."""
    dz, tilt = box['position'][2]-target[2], math.acos(max(-1., min(1., rotation_matrix(box['orientation'])[2][2])))
    return dict(dz_mm=round(dz*1e3, 3), tilt_deg=round(math.degrees(tilt), 3),
                seated=abs(dz) <= limits['height_m'] and tilt <= limits['tilt_rad'])


def leveling_center(fixture, arm):
    """The leveling spot `arm` uses: its own (`leveling_centers_m`, one per arm) or the shared `leveling_center_m`."""
    centers = fixture.get('leveling_centers_m')
    return centers[arm] if centers else fixture['leveling_center_m']


def leveling_via(fixture, arm):
    """The waypoint `arm` passes on its way to and from leveling: its own (`leveling_vias_m`, None for none) or the shared one."""
    vias = fixture.get('leveling_vias_m')
    return vias[arm] if vias else fixture.get('leveling_via_m')
