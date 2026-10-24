"""Frozen synthetic tray/belt fixture and independent contact-task criteria."""
import hashlib
import json
import math

PINKY = (.14, -.07, .09)
CONVEYOR = (.14, .07, .09)
CARGO_SIZE = .018
DT = 1 / 120
FIXTURE = dict(revision='stationary-proxy-v1', coordinate_scope='SYNTHETIC_NOT_CAMERA_REGISTERED',
    pinky_support_m=PINKY, conveyor_surface_m=CONVEYOR, cargo_size_m=CARGO_SIZE,
    cargo_mass_kg=.05, physics_dt_s=DT, gravity_m_s2=9.81, friction=1., restitution=0.,
    pinky_representation='STATIC_TRAY_PROXY_NOT_FULL_ROBOT', belt_speed_m_s=0.,
    controller='DETERMINISTIC_CAD_IK_NOT_LEARNED_POLICY', attachment_aid=False,
    xy_tolerance_m=.015, z_tolerance_m=.005, tilt_tolerance_deg=10.,
    speed_tolerance_m_s=.01, settle_seconds=1., minimum_lift_m=.02)


def fixture_sha256():
    return hashlib.sha256(json.dumps(FIXTURE, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def forward(q):
    """Pinned OMX-F end_effector_link, base=world, roll joint5=0 (metres/radians)."""
    yaw, a, b, c, roll = q
    if abs(roll) > 1e-10:
        raise ValueError('This fixed vertical grasp requires joint5=0')
    pitch = a+b+c
    radial = (.0415*math.cos(a)+.11315*math.sin(a)+.162*math.cos(a+b)
              +.12063*math.cos(pitch))
    z = .0975+.11315*math.cos(a)-.0415*math.sin(a)-.162*math.sin(a+b)-.12063*math.sin(pitch)
    return [math.cos(yaw)*radial+.0016*math.sin(yaw)-.01125,
            math.sin(yaw)*radial-.0016*math.cos(yaw), z]


def solve(position):
    """Closed-form downward grasp; refuse unreachable or out-of-limit poses."""
    x, y, z = position
    if not all(math.isfinite(v) for v in position):
        raise ValueError('Finite target required')
    radius2 = (x+.01125)**2+y*y-.0016**2
    if radius2 <= 0:
        raise ValueError('Target on yaw singularity')
    radial = math.sqrt(radius2)
    yaw = math.atan2(y, x+.01125)-math.atan2(-.0016, radial)
    height = z-.0975+.12063
    first = math.hypot(.0415, .11315)
    cosine = (radial**2+height**2-first**2-.162**2)/(2*first*.162)
    if not -1 <= cosine <= 1:
        raise ValueError('Target outside OMX-F reach')
    beta = math.acos(cosine)
    alpha = math.atan2(.11315, .0415)
    a = alpha-math.atan2(height, radial)-math.atan2(.162*math.sin(beta), first+.162*cosine)
    b = beta-alpha
    q = [yaw, a, b, math.pi/2-a-b, 0.]
    if any(abs(v) > 2*math.pi for v in q):
        raise ValueError('Joint limit exceeded')
    return q


def evaluate(samples):
    """Read measured samples only; no controller acknowledgement counts as success."""
    failures = []
    phases = ['pinky_initial', 'out_lift', 'out_transport', 'conveyor_settle',
              'back_lift', 'back_transport', 'pinky_settle']
    groups = {phase: [] for phase in phases}
    last_tick, order = -1, -1
    try:
        for row in samples:
            tick = row['tick']
            fields = [('position', 3), ('orientation', 4), ('linear_velocity', 3),
                      ('angular_velocity', 3), ('contact_forces', 4)]
            if type(tick) is not int or not last_tick < tick <= 4800:
                raise ValueError('nonadvancing_or_unbounded_clock')
            for key, count in fields:
                if len(row[key]) != count or not all(type(v) in (int, float) and math.isfinite(v) for v in row[key]):
                    raise ValueError('invalid_measurement')
            for key in ('tool_distance', 'joint_error', 'tcp_error'):
                if not math.isfinite(row[key]) or row[key] < 0:
                    raise ValueError('invalid_tracking')
            if abs(sum(v*v for v in row['orientation'])-1) > .001:
                raise ValueError('invalid_orientation')
            last_tick = tick
            if row['phase'] in groups:
                current = phases.index(row['phase'])
                if current < order:
                    raise ValueError('phase_order')
                order = current
                groups[row['phase']].append(row)
        for phase, rows in groups.items():
            if len(rows) < 2 or rows[-1]['tick']-rows[0]['tick'] < 120:
                failures.append(phase+':incomplete_window')
                continue
            if any(b['tick']-a['tick'] != 4 for a, b in zip(rows, rows[1:])):
                failures.append(phase+':missing_observations')
            if any(r['joint_error'] > .08 or r['tcp_error'] > .008 for r in rows[-31:]):
                failures.append(phase+':tracking')
            if 'lift' in phase or 'transport' in phase:
                contact = [r for r in rows if min(r['contact_forces'][:2]) > .02
                           and r['position'][2] >= PINKY[2]+CARGO_SIZE/2+.02
                           and max(r['contact_forces'][2:]) < .02]
                if len(contact)/len(rows) < .8:
                    failures.append(phase+':no_bilateral_free_lift')
            else:
                target, support = (CONVEYOR, 3) if phase == 'conveyor_settle' else (PINKY, 2)
                for r in rows[-31:]:
                    p, q = r['position'], r['orientation']
                    if (math.hypot(p[0]-target[0], p[1]-target[1]) > .015
                            or abs(p[2]-target[2]-CARGO_SIZE/2) > .005
                            or 1-2*(q[1]**2+q[2]**2) < math.cos(math.radians(10))
                            or math.sqrt(sum(v*v for v in r['linear_velocity'])) > .01
                            or math.sqrt(sum(v*v for v in r['angular_velocity'])) > .1
                            or r['contact_forces'][support] <= .02
                            or max(r['contact_forces'][:2]) > .02 or r['tool_distance'] < .04):
                        failures.append(phase+':not_released_and_settled')
                        break
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        failures.append('invalid_observation:'+str(exc))
    return dict(task_success=not failures, failures=failures,
                evidence_class='PHYSICS_GRASP' if not failures else 'INCOMPLETE_CONTACT_TASK')
