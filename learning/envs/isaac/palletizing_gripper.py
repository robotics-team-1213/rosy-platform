"""Palletizing jaw v2.1 (omx_f_palletizing_description): contact pads, finger angles and TCP from the vendored files.

Everything is read from the vendored URDF and jaw STL, nothing is typed in: the pad is the innermost large flat face of
the jaw6 mesh that looks toward the other jaw (the raised tape-side pad), jaw7 is its mirror. Stdlib only, because the
Isaac adapter runs on the Isaac SDK's own Python and the planner on the system Python.
"""
from functools import lru_cache
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

ASSETS = Path(__file__).resolve().parent/'assets/omx_f_palletizing_description'
URDF = ASSETS/'urdf/omx_f_palletizing.urdf'
GRIPPER = 'palletizing-v2.1'
PAD_THICKNESS_M = .0015  # pad bulk behind the contact face (the jaw plate behind it is 0.9 to 2 mm)
PAD_CONTACT_OFFSET_M, PAD_REST_OFFSET_M = .001, 0.
SQUEEZE_M = .003  # same total squeeze as cell_profile.yaml gripper.jaw.squeeze_m
PREOPEN_GAP_M, GRASP_WIDTH_M, RELEASE_GAP_M = .036, .03, .04  # as isaac_stack_plan.py asks the old gripper for


def _triangles(path):
    data = Path(path).read_bytes()
    count = struct.unpack_from('<I', data, 80)[0]
    if len(data) != 84+50*count:
        raise ValueError(f'{path} is not a binary STL')
    return [struct.unpack_from('<9f', data, 84+50*i+12) for i in range(count)]


@lru_cache(maxsize=None)
def description():
    """Joint origins in link5 and the TCP from the vendored URDF."""
    root = ET.parse(URDF).getroot()

    def xyz(joint):
        return tuple(float(v) for v in root.find(f"joint[@name='{joint}']/origin").get('xyz').split())
    return dict(tcp=xyz('end_effector_joint'), pivots=(xyz('gripper_joint_1'), xyz('gripper_joint_2')))


@lru_cache(maxsize=None)
def pad():
    """The jaw6 contact pad in the link6 frame, metres: normal angle toward the other jaw, face offset, extents."""
    faces = []  # (area, outward normal xy, vertices, centroid)
    for t in _triangles(ASSETS/'meshes/omx_f/palletizing_jaw6_servo_side_v2_1.stl'):
        a, b, c = (t[0:3], t[3:6], t[6:9])
        u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        length = math.sqrt(sum(x*x for x in n))
        centroid = [sum(p[i] for p in (a, b, c))/3 for i in range(3)]
        if length > 0 and abs(n[2]) < .02*length and n[1] < -.5*length and centroid[0] > 20:  # jaw6 faces -y
            faces.append((length/2, (n[0]/length, n[1]/length), (a, b, c), centroid))
    rough = math.atan2(*max(faces)[1][::-1])  # the largest triangle's direction: only to measure reach along the finger
    reach = lambda f: max(p[0]*math.cos(rough+math.pi/2)+p[1]*math.sin(rough+math.pi/2) for p in f[2])  # noqa: E731
    tip = max(reach(f) for f in faces)
    planes = {}  # one plane = faces of the same normal direction (0.05 deg) and offset (0.05 mm)
    for f in faces:
        if reach(f) > .9*tip:  # only faces reaching the fingertip belong to the finger plate, not the jaw body
            heading = math.atan2(f[1][1], f[1][0])
            d = -(f[3][0]*f[1][0]+f[3][1]*f[1][1])  # toward the other jaw: n_p = -outward
            planes.setdefault((round(math.degrees(heading)/.05), round(d/.05)), []).append(f)
    # shortcut: the innermost plane with at least 100 mm2 is the pad; a jaw with a second inner face needs a rule.
    face = min(k for k, fs in planes.items() if sum(f[0] for f in fs) >= 100)
    area = sum(f[0] for f in planes[face])
    angle = math.atan2(-sum(f[0]*f[1][1] for f in planes[face]), -sum(f[0]*f[1][0] for f in planes[face]))  # n_p
    tangent = angle+math.pi/2
    points = [p for f in planes[face] for p in f[2]]
    nx, ny = math.cos(angle), math.sin(angle)
    d = sum(-(f[3][0]*f[1][0]+f[3][1]*f[1][1])*f[0] for f in planes[face])/area
    along = [p[0]*math.cos(tangent)+p[1]*math.sin(tangent) for p in points]
    return dict(angle=angle, normal=(nx, ny), offset=d/1000, tangent=tangent, along=(min(along)/1000, max(along)/1000),
                z=(min(p[2] for p in points)/1000, max(p[2] for p in points)/1000),
                corners=[(p[0]/1000, p[1]/1000, p[2]/1000) for p in points])


def pad_box(side):
    """(centre xyz, size (thickness, length, width), rotation about z) of one finger's pad box in its link frame.

    side is +1 for link6 and -1 for link7, the mirror in y. The box is rotated so its x axis is the pad normal.
    """
    p = pad()
    lo, hi = p['along']
    mid = (lo+hi)/2
    centre = [p['normal'][0]*(p['offset']+PAD_THICKNESS_M/2)+math.cos(p['tangent'])*mid,
              p['normal'][1]*(p['offset']+PAD_THICKNESS_M/2)+math.sin(p['tangent'])*mid, (p['z'][0]+p['z'][1])/2]
    return ((centre[0], side*centre[1], centre[2]), (PAD_THICKNESS_M, hi-lo, p['z'][1]-p['z'][0]),
            p['angle'] if side > 0 else -p['angle'])


def _plane(side, q):
    """Pad face in link5 coordinates at lead angle q (the follower mirrors it): unit normal toward the other jaw, offset."""
    pivot = description()['pivots'][0 if side > 0 else 1]
    p = pad()
    turn = p['angle']*side+side*q  # link6 turns by +q, link7 by -q about z, with the mirrored pad normal
    normal = (math.cos(turn), math.sin(turn))
    return normal, normal[0]*pivot[0]+normal[1]*pivot[1]+p['offset']


def gap_m(q):
    """Smallest distance between the two pad faces at finger angle q: the width of the item they just touch."""
    best = math.inf
    for side, other in ((1, -1), (-1, 1)):
        o_normal, o_offset = _plane(other, q)
        pivot = description()['pivots'][0 if side > 0 else 1]
        for c in pad()['corners']:
            x, y = c[0], c[1]*side
            cos, sin = math.cos(side*q), math.sin(side*q)
            ax, ay = pivot[0]+cos*x-sin*y, pivot[1]+sin*x+cos*y  # corner in link5 coordinates
            # positive on the free side of the other jaw's pad plane, negative when the pads would overlap
            best = min(best, o_offset-(o_normal[0]*ax+o_normal[1]*ay))
    return best


def angle_for_gap(width_m):
    lo, hi = -.2, 1.2  # gap grows with the lead angle (+ = open)
    if not gap_m(lo) <= width_m <= gap_m(hi):
        raise ValueError('width is outside the palletizing jaw stroke')
    for _ in range(60):
        mid = (lo+hi)/2
        lo, hi = (mid, hi) if gap_m(mid) < width_m else (lo, mid)
    return (lo+hi)/2


def finger_angles(release_gap_m=None):
    """Pre-open, squeezing close and release angles for the 30 mm container, from the pad geometry."""
    return dict(preopen=angle_for_gap(PREOPEN_GAP_M), close=angle_for_gap(GRASP_WIDTH_M-SQUEEZE_M),
                release=angle_for_gap(release_gap_m or RELEASE_GAP_M))


def pad_sweep_bottom_relative_tcp(row):
    """Lowest point any pad corner can reach, relative to the TCP, for a wrist whose rotation matrix's third row is `row`.

    The pad swings about its pivot as the finger turns, so (like the capsule version) the worst case is a full circle
    at the pad's farthest corner.
    """
    info, bottoms = description(), []
    for k, pivot in enumerate(info['pivots']):
        reach = max(math.hypot(c[0], c[1]) for c in pad()['corners'])
        half_z = max(abs(c[2]) for c in pad()['corners'])
        sweep = math.hypot(row[0], row[1])*reach
        bottoms.append(sum(row[i]*(pivot[i]-info['tcp'][i]) for i in range(3))-sweep-half_z*abs(row[2])-PAD_CONTACT_OFFSET_M)
    return min(bottoms)


# Wrist camera on the printed D holder b16-u16-span-D, r06 balanced tilt (rosy-docs hardware/omx-wrist-camera-mount,
# out/results.json, 2026-11-07): lens and the point where the optical axis meets the jaw axis, link5 metres; vertical
# FOV over the 720 rows of the 1280x720 sensor; lowest holder point above the TCP in the top-down pose.
WRIST_CAMERA_B = dict(name='b16-u16-span-D', lens_m=[.0338, 0., .0511], axis_hit_x_m=.1078, vfov_deg=69.6,
                      sensor=[1280, 720], lowest_above_tcp_m=.0362)  # lists: the fixture is compared after JSON


def wrist_camera_pose(spec=WRIST_CAMERA_B):
    """(position, quaternion w x y z) of the wrist camera in link5 for a camera that looks along its -Z with +Y up (USD and
    MuJoCo). The optical axis lies in the link5 x-z plane; image up points back toward the wrist (-x side), ASSUMED until
    compared with a real wrist frame."""
    lx, _, lz = spec['lens_m']
    n = math.hypot(spec['axis_hit_x_m']-lx, lz)
    d = ((spec['axis_hit_x_m']-lx)/n, 0., -lz/n)
    up = (d[2], 0., -d[0])  # perpendicular to d in the x-z plane, x component < 0 (toward the wrist)
    z = tuple(-c for c in d)
    x = (up[1]*z[2]-up[2]*z[1], up[2]*z[0]-up[0]*z[2], up[0]*z[1]-up[1]*z[0])
    m = [[x[i], up[i], z[i]] for i in range(3)]  # columns are the camera axes in link5
    w = math.sqrt(max(0., 1+m[0][0]+m[1][1]+m[2][2]))/2
    q = (w, (m[2][1]-m[1][2])/(4*w), (m[0][2]-m[2][0])/(4*w), (m[1][0]-m[0][1])/(4*w))
    return spec['lens_m'], q
