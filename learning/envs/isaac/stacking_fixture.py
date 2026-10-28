"""Synthetic two-arm cell in metres; 30 mm units and a strict 90 mm cargo envelope."""
import math
import hashlib
from pathlib import Path

UNIT = .03
BIN_ORIGIN = (.155, -.025, .025)
BELT_TOP = .025
DT = 1 / 120
PROFILE = Path(__file__).resolve().parents[3]/'deploy/robot/omx/sim/cell_profile.yaml'
FIXTURE = dict(revision='omx-stacking-v1', coordinate_scope='SYNTHETIC_NOT_CAMERA_REGISTERED',
               unit_m=UNIT, bin_origin_m=BIN_ORIGIN, bin_size_m=[.09]*3,
               arm_bases_m=[[0., -.14, 0.], [0., .14, 0.]],
               belt_size_m=[.12, .50, .025], belt_speed_m_s=.02,
               robot_self_collision=False,
               control_profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
               attachment_aid=False, physics_dt_s=DT, control_decimation=4,
               xy_tolerance_m=.0015, z_tolerance_m=.0015, settle_steps=30,
               seed_effect='CARGO_RESET_XY_AND_YAW', num_envs=1,
               iterations=32, steps_per_update=32, evaluation_seed_offset=10000)


def advance_joint(position, velocity, requested_velocity, limits, dt):
    """Apply the existing nominal SIM velocity/acceleration limits before the servo target."""
    if not all(math.isfinite(v) for v in (position, velocity, requested_velocity, dt)) or dt <= 0:
        raise ValueError('Finite joint command and positive control interval required')
    vmax, amax = limits['velocity'], limits['acceleration']
    low, high = limits['position']
    # Euler target integration includes one control interval before subsequent braking.
    def braking_speed(distance):
        return (math.sqrt((amax*dt)**2+8*amax*max(0., distance))-amax*dt)/2
    requested_velocity = max(-min(vmax, braking_speed(position-low)),
                             min(vmax, braking_speed(high-position), requested_velocity))
    velocity += max(-amax*dt, min(amax*dt, requested_velocity-velocity))
    wanted = position+velocity*dt
    if wanted < low-1e-12 or wanted > high+1e-12:
        raise ValueError('Previous joint command cannot stop within the profile')
    bounded = max(low, min(high, wanted))
    return bounded, velocity


def stack_plan():
    plan = []
    for z in range(3):
        for y, lengths in enumerate(((3,), (2, 1), (1, 2))):
            x = 0
            for length in lengths:
                plan.append(dict(cell=[x, y, z], cells=length,
                                 arm=0 if y == 0 else 1))
                x += length
    return plan


def target(item):
    x, y, z = item['cell']
    return [BIN_ORIGIN[0]+UNIT*(x+item['cells']/2),
            BIN_ORIGIN[1]+UNIT*(y+.5), BIN_ORIGIN[2]+UNIT*(z+.5)]


def placed(item, *, position, orientation, speed, finger_force, support_force, lifted):
    values = [*position, *orientation, speed, finger_force, support_force]
    if (len(position) != 3 or len(orientation) != 4 or
            not all(math.isfinite(v) for v in values) or not lifted):
        return False
    norm = sum(v*v for v in orientation)
    w, x, y, z = orientation
    # Sideways or yawed cargo cannot satisfy a tightly packed rectangular footprint.
    if abs(norm-1) > .01 or abs(w) < math.cos(math.radians(1.5)):
        return False
    rotation = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
                (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
                (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    half = (UNIT*item['cells']/2, UNIT/2, UNIT/2)
    for axis in range(3):
        extent = sum(abs(rotation[axis][j])*half[j] for j in range(3))
        if (position[axis]-extent < BIN_ORIGIN[axis]-.0002 or
                position[axis]+extent > BIN_ORIGIN[axis]+.09+.0002):
            return False
    goal = target(item)
    return (all(abs(position[i]-goal[i]) <= .0015 for i in range(3))
            and speed < .01 and finger_force < .001 and support_force > .001)
