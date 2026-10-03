"""The vectorised wall fit must reproduce the original pure-Python fit exactly.

The /scan wall tracker was 75% of the calibration node's CPU in the loaded sim rig
(2026-09-23): about 130 _fit calls per scan, 28 ms per scan on an idle x86 core.
The optimisation is only acceptable if every fit, segment list and tracker
diagnostic is bit-identical, with plain Python floats (diagnostics are stringified).
"""
import math
import random
from statistics import median
from types import SimpleNamespace as NS

import control.sensing.wall_tracker as wall_tracker
from control.sensing.wall_tracker import WallTracker, _segments


def reference_fit(points, allow_exclusion=True):
    """Verbatim copy of wall_tracker._fit before vectorisation (main 860a6740)."""
    if len(points) < 6 or points[-1][0]-points[0][0] < math.radians(5):
        return None
    quarter = max(1, len(points)//4)
    slopes = [(q[2]-p[2])/(q[1]-p[1]) for p in points[:quarter]
              for q in points[-quarter:] if abs(q[1]-p[1]) > 1e-6]
    if not slopes:
        return None
    a = median(slopes)
    b = median(x-a*y for _, y, x in points)
    errors = [abs(x-a*y-b)/math.hypot(1., a) for _, y, x in points]
    residual = max(errors)
    if abs(a) > 2.5 or not .05 < b < 8.:
        return None
    if residual > .003:
        excluded = [i for i, error in enumerate(errors) if error > .003]
        if (not allow_exclusion or len(excluded) > .1*len(points) or residual > .010
                or any(j == i+1 for i, j in zip(excluded, excluded[1:]))):
            return None
        fit = reference_fit([p for i, p in enumerate(points) if i not in excluded], False)
        if fit is None:
            return None
        raw_residual = max(abs(x-fit['slope']*y-fit['intercept'])/math.hypot(1., fit['slope'])
                           for _, y, x in points)
        if raw_residual > .010:
            return None
        fit.update(excluded_rays=len(excluded), raw_residual_m=raw_residual,
                   _raw_points=tuple(points))
        return fit
    return {'slope': a, 'intercept': b, 'lo': points[0][0],
            'hi': points[-1][0], 'rays': len(points), 'residual_m': residual,
            'excluded_rays': 0, 'raw_residual_m': residual, 'outlier_cap_m': .010,
            '_points': tuple(points), '_raw_points': tuple(points)}


def plain(value):
    """Exact structural equality, with every number a builtin float/int (never numpy)."""
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(plain(item) for item in value)
    assert type(value) in (float, int, bool, str, type(None)), (type(value), value)
    # repr, not ==: -0.0 == 0.0, but a stringified diagnostic prints the sign.
    return repr(value) if type(value) is float else value


def wall_points(rng, n, distance, slope, noise, outliers=0, span_deg=30., dup=False):
    """(angle, y, x) rays on the line x = slope*y + distance, sorted by angle."""
    points = []
    for i in range(n):
        angle = math.radians(-span_deg/2+span_deg*i/max(1, n-1))
        y = distance*math.tan(angle)
        if dup and i % 7 == 3 and points:
            y = points[-1][1]
        x = slope*y+distance+rng.gauss(0., noise)
        points.append((angle, round(y, 4), round(x, 3)))
    for _ in range(outliers):
        i = rng.randrange(n)
        a, y, x = points[i]
        points[i] = (a, y, x+rng.choice((-1, 1))*rng.uniform(.003, .015))
    return points


def fit_cases():
    rng = random.Random(20260923)
    cases = [[], [(0., 0., .3)]*5, wall_points(rng, 6, .3, 0., 0., span_deg=4.)]
    for _ in range(3000):
        cases.append(wall_points(
            rng, rng.randint(4, 90), rng.uniform(.03, 9.), rng.uniform(-3., 3.),
            rng.choice((0., .0005, .001, .002, .004, .012)), outliers=rng.choice((0, 0, 1, 2, 5)),
            span_deg=rng.uniform(2., 70.), dup=rng.random() < .2))
    return cases


def near_duplicate_cases():
    """First/last-quarter pairs whose y differ by 0..1e-4: the 1e-6 pair filter decides them.

    A straight wall scanned in angle order has monotonic y, but compensated runs and runs
    across a corner need not; a wrong pair filter changes the slope median there.
    """
    rng = random.Random(611)
    cases = []
    for _ in range(1500):
        n = rng.randint(6, 24)
        slope, distance = rng.uniform(-.3, .3), rng.uniform(.2, 2.)
        ys = sorted(rng.uniform(-.2, .2) for _ in range(n))
        quarter = max(1, n//4)
        for k in range(quarter):
            source = rng.randrange(quarter)
            ys[n-1-k] = ys[source]+rng.choice((0., 5e-7, 2e-6, 3e-5, 8e-5))
        points = [(math.radians(8.*i/(n-1)), y, slope*y+distance+rng.gauss(0., .0004))
                  for i, y in enumerate(ys)]
        cases.append(points)
    return cases


def test_pair_filter_matches_on_near_duplicate_offsets():
    differs = 0
    for points in near_duplicate_cases():
        expected = reference_fit(points)
        assert plain(wall_tracker._fit(points)) == plain(expected), points
        differs += expected is not None
    assert differs > 50  # accepted fits exist, so the pair set actually matters


def test_signed_zero_slopes_keep_the_original_sign():
    # Exactly equal x over non-monotonic y yields slopes of +0.0 and -0.0; statistics.median
    # sorts stably, so the sign of a zero median depends on input order (review 2026-09-23).
    rng = random.Random(29)
    signed = 0
    for _ in range(3000):
        n = rng.randint(24, 120)
        ys = [rng.uniform(-.3, .3) for _ in range(n)]
        points = [(math.radians(10.*i/(n-1)), y, .5) for i, y in enumerate(ys)]
        expected = reference_fit(points)
        assert plain(wall_tracker._fit(points)) == plain(expected), points
        signed += expected is not None and expected['slope'] == 0.
    assert signed > 1000


def test_fit_is_identical_to_the_original_on_varied_walls():
    accepted = excluded = 0
    for points in fit_cases():
        expected = reference_fit(points)
        assert plain(wall_tracker._fit(points)) == plain(expected), points
        accepted += expected is not None
        excluded += bool(expected and expected['excluded_rays'])
    # The corpus must exercise the accept, reject and single-exclusion branches.
    assert accepted > 300 and excluded > 30 and accepted < 2900


def scan(front, side, nose=0., noise=.0005, seed=0, n=720, gaps=0):
    rng = random.Random(seed)
    ranges = []
    for i in range(n):
        a = -math.pi+i*math.tau/n+nose
        dx, dy = math.cos(a), math.sin(a)
        t = min(front/dx if dx > 1e-9 else 1e9, side/abs(dy) if abs(dy) > 1e-9 else 1e9,
                2./abs(dx) if dx < -1e-9 else 1e9)
        ranges.append(round(t+rng.gauss(0., noise), 3))
    for _ in range(gaps):
        ranges[rng.randrange(n)] = rng.choice((math.inf, math.nan, 0.))
    return NS(ranges=ranges, angle_min=-math.pi, angle_increment=math.tau/n, range_min=.05, range_max=12.)


def reference_segment_fit(points, allow_exclusion=True, array=None):
    """The reference ignores the hot-path array; it always recomputes from the tuples."""
    return reference_fit(points, allow_exclusion)


def with_reference(call):
    original = wall_tracker._fit
    wall_tracker._fit = reference_segment_fit
    try:
        return call()
    finally:
        wall_tracker._fit = original


def scan_cases():
    rng = random.Random(7)
    for k in range(60):
        yield (scan(rng.uniform(.15, 1.5), rng.uniform(.2, 1.), noise=rng.choice((0., .0005, .002)),
                    seed=k, gaps=rng.choice((0, 3, 20))),
               rng.uniform(-.2, .2),
               None if k % 3 else (rng.uniform(-.05, .05), rng.uniform(-.01, .01), (.02, .0), (.02, .0)))


def test_segments_are_identical_to_the_original():
    for data, nose, compensation in scan_cases():
        expected = with_reference(lambda: _segments(data, nose, compensation))
        assert plain(_segments(data, nose, compensation)) == plain(expected)


def split_front(data, rays=2):
    """Blank the rays straight ahead so the tracked wall arrives as two fragments."""
    middle = min(range(len(data.ranges)), key=lambda i: abs(data.angle_min+i*data.angle_increment))
    for i in range(middle-rays//2, middle+rays-rays//2):
        data.ranges[i] = math.inf
    return data


def test_tracker_fragment_merge_is_identical_to_the_original():
    def run():
        tracker, out = WallTracker(), []
        for k in range(10):
            data = scan(.4, .6, noise=0., seed=k)
            out.append((tracker.update(split_front(data) if k >= 4 else data, 0.), dict(tracker.diagnostic)))
        return out
    expected = with_reference(run)
    assert any('fragments' in diagnostic for _, diagnostic in expected)  # merged _fit(points) ran
    assert plain(run()) == plain(expected)


def test_tracker_sequence_is_identical_to_the_original():
    def run():
        tracker, out = WallTracker(), []
        for k in range(12):
            pose = (.001*k, .0002*k, .002*k)
            out.append((tracker.update(scan(.4, .6, noise=.0005, seed=k), 0., locked=k > 5,
                                       pose=pose, mount=(.02, 0.), now=10.+.1*k),
                        dict(tracker.diagnostic)))
        return out
    expected = with_reference(run)
    assert plain(run()) == plain(expected)
