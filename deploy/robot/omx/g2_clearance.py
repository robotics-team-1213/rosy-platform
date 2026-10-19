"""Reviewed OMX SIM fixture check, limited to nominal vertical finger descent.

This is not a collision planner or runtime contact acceptance. Full-open retreat,
interpolated travel, the rest of the arm and actual stalled jaw positions are uncovered.
"""
from hashlib import sha256
import math
from pathlib import Path
import struct

_MESHES = (
    ('follower_07_gripper_motorized.stl', .0075, 1,
     'd3811b2c5f6d34bd60f10c42e1a481f16ec1f9117cf944604009691f62c1d6ac'),
    ('follower_08_gripper_gear.stl', -.0108, -1,
     '6a492837011578baeec1dca15a493c7af81bf812917c8846f48d1d75a76647ab'),
)
_KINEMATICS = '27cd572830f931b57eedec55081b77749f65dcd059d11e34199bdcb1bb6db04d'
_TRANSFORMS = {
    'omx_f.urdf': 'd06720f50c71b380daa91f6cf52ae089725bc588617e5f42ed2433b6e665b809',
    'omx_f.urdf.xacro': '63ea4bf15d758a6f7124052134640e9de74a0380c88c9b6d3803b852d0956f25',
    'omx_f_arm.urdf.xacro': 'bf5f9cb463f2c43e6a48a520a3496659fd9cc377f775f6c5d080c3d11776a527',
}


def _number(value):
    if type(value) not in (float, int) or not math.isfinite(value) or abs(value) > 1:
        raise ValueError('UNSUPPORTED: bounded finite SIM fixture coordinates required')
    return float(value)


def _hull(points):
    points = sorted(set(points))
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def half(ordered):
        result = []
        for point in ordered:
            while len(result) > 1 and cross(result[-2], result[-1], point) <= 0:
                result.pop()
            result.append(point)
        return result
    return half(points)[:-1]+half(reversed(points))[:-1]


def _clip(poly, cutoff):
    result = []
    for a, b in zip(poly, poly[1:]+poly[:1]):
        if a[0] >= cutoff:
            result.append(a)
        if (a[0] < cutoff) != (b[0] < cutoff):
            fraction = (cutoff-a[0])/(b[0]-a[0])
            result.append((cutoff, a[1]+fraction*(b[1]-a[1])))
    return result


def _meshes(directory, require_sdk_transforms):
    result, hashes = [], {}
    for name, pivot, multiplier, expected in _MESHES:
        path = Path(directory)/name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError('UNSUPPORTED: reviewed finger mesh unavailable')
        data = path.read_bytes()
        if sha256(data).hexdigest() != expected:
            raise ValueError('UNSUPPORTED: finger mesh geometry differs from reviewed asset')
        hashes[name] = expected
        count = struct.unpack_from('<I', data, 80)[0]
        if len(data) != 84+50*count:
            raise ValueError('UNSUPPORTED: unexpected STL encoding')
        vertices = set(tuple(v*.001 for v in struct.unpack_from('<fff', data, 84+50*i+12+12*j))
                       for i in range(count) for j in range(3))
        if max(math.hypot(x, y) for x, y, z in vertices) > .12:
            raise ValueError('UNSUPPORTED: finger exceeds angular sampling radius')
        result.append((vertices, pivot, multiplier))
    transforms = {}
    for name, expected in _TRANSFORMS.items():
        if name != 'omx_f.urdf' and not require_sdk_transforms:
            continue
        path = Path(directory).parents[1]/'urdf/omx_f'/name
        if (not path.is_file() or path.stat().st_size > 100_000
                or sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected):
            raise ValueError('UNSUPPORTED: vendor TCP or gripper transforms changed')
        transforms[name] = expected
    return result, hashes, transforms


def _supported(profile, box):
    expected = dict(length=.04, width=.03, height=.03, grasp_depth=.015)
    if any(not math.isclose(_number(box.get(key)), value, abs_tol=1e-12) for key, value in expected.items()):
        raise ValueError('UNSUPPORTED: unreviewed box geometry')
    facts = (profile.jaw_pivot_half_separation_m, *profile.jaw_contact_point_m,
             profile.gripper_squeeze_m, profile.gripper_release_clearance_m, profile.start_state_tolerance_rad)
    if (profile.kinematics_revision != _KINEMATICS
            or any(not math.isclose(a, b, abs_tol=1e-12) for a, b in
                   zip(facts, (.00915, .0543, -.01703, .003, .01, .02)))):
        raise ValueError('UNSUPPORTED: unreviewed TCP or jaw geometry')


def check_clearance(job, profile, mesh_directory, *, box, require_sdk_transforms=False):
    """Reject known nominal descent interference; never assert full motion clearance."""
    _supported(profile, box)
    if not isinstance(job.get('steps'), list) or len(job['steps']) > 40:
        raise ValueError('UNSUPPORTED: fixture job shape')
    targets = []
    for step in job['steps']:
        if step['kind'] != 'place' or step.get('item') != 'box':
            continue
        target = {key: _number(step['target'][key]) for key in ('x', 'y', 'z', 'yaw')}
        if abs(math.remainder(target['yaw'], math.pi)) > 1e-10:
            raise ValueError('UNSUPPORTED: nominal descent yaw is not a reviewed twin')
        targets.append(target)
    if len(targets) != 16:
        raise ValueError('UNSUPPORTED: fixture requires 16 box placements')
    meshes, hashes, transforms = _meshes(mesh_directory, require_sdk_transforms)
    low = profile.gripper_close_for_width(.03)
    high = profile.gripper_contact_for_width(.04)+.02
    intervals = math.ceil((high-low)/.002)
    angular_pad = .12*(high-low)/intervals/2
    inflation = .002+angular_pad
    # TCP = link5 * (.09193,-.0016,0); gripper origins are reviewed URDF constants.
    cutoffs = {current['z']+.09193-(prior['z']+.015)-angular_pad
               for index, current in enumerate(targets) for prior in targets[:index]}
    envelopes = {cutoff: None for cutoff in cutoffs}
    for vertices, pivot, multiplier in meshes:
        for index in range(intervals+1):
            angle = multiplier*(low+(high-low)*index/intervals)
            points = [(.0295+math.cos(angle)*x-math.sin(angle)*y,
                       pivot+math.sin(angle)*x+math.cos(angle)*y+.0016, z) for x, y, z in vertices]
            # Projections of the convex hull give conservative slab-restricted AABBs.
            # The expanded cutoff and XY inflation cover between-sample angular motion.
            x_projection = _hull([(x, z) for x, y, z in points])
            y_projection = _hull([(x, y) for x, y, z in points])
            for cutoff in cutoffs:
                xs, ys = _clip(x_projection, cutoff), _clip(y_projection, cutoff)
                if not xs or not ys:
                    continue
                ex = max(abs(point[1]) for point in xs)+inflation
                ey = max(abs(point[1]) for point in ys)+inflation
                old = envelopes[cutoff]
                envelopes[cutoff] = (max(ex, old[0]) if old else ex, max(ey, old[1]) if old else ey)
    minimum = 1.
    for index, current in enumerate(targets):
        for prior_index, prior in enumerate(targets[:index]):
            envelope = envelopes[current['z']+.09193-(prior['z']+.015)-angular_pad]
            if envelope is None:
                continue  # A lower support box is vertically clear of these finger hulls.
            separation = max(abs(prior['x']-current['x'])-.02-envelope[0],
                             abs(prior['y']-current['y'])-.015-envelope[1])
            minimum = min(minimum, separation)
            if separation <= 0:
                raise ValueError(f'NOMINAL_FINGER_INTERFERENCE: placement {index} against prior {prior_index}')
    return dict(scope='NOMINAL_DESCENT_FINGER_ENVELOPE_ONLY', box_count=16, ordered_pairs=120,
                minimum_separation_beyond_inflation_m=minimum, inflation_m=inflation,
                q_interval_rad=[low, high], q_samples=intervals+1, mesh_sha256=hashes,
                transform_sha256=transforms,
                actual_stall_measured=False, uncovered=['full_open_retreat', 'nonvertical_interpolation',
                                                       'whole_arm', 'slip_sheet_contacts', 'actual_contacts', 'hardware'])
